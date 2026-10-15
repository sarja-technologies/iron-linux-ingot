"""Global configuration, host resources and per-agent resource presets."""
import configparser
import json
import os
import re
from dataclasses import asdict, dataclass, field

CONF_PATH = os.environ.get("IRON_AGENTS_CONF", "/etc/iron/agent-desktops.conf")
STATE_DIR = os.environ.get("IRON_AGENTS_STATE", "/var/lib/iron/agents")
IMAGE_DIR = os.environ.get("IRON_AGENTS_IMAGES", "/var/lib/iron/agent-images")
RUN_DIR = os.environ.get("IRON_AGENTS_RUN", "/run/iron/agents")
HARDWARE_JSON = "/run/iron/hardware.json"

BACKENDS = ("container", "vm")
NETWORK_MODES = ("none", "internet")
GPU_MODES = ("none", "shared")


class ConfigError(ValueError):
    """Invalid user-supplied configuration (reported back over D-Bus)."""


@dataclass
class GlobalConfig:
    enabled: bool = False
    max_agents: int = 3
    # Upper bounds an ordinary (non-admin) user may allocate, as host fractions.
    user_max_cpu_fraction: float = 0.5
    user_max_memory_fraction: float = 0.5
    # Memory always kept for the host desktop, regardless of allocations.
    host_reserved_memory_mib: int = 2048
    default_backend: str = "container"
    idle_exit_seconds: int = 60

    @classmethod
    def load(cls, path=None):
        path = path or CONF_PATH
        cp = configparser.ConfigParser()
        cp.read(path)
        s = cp["agent-desktops"] if cp.has_section("agent-desktops") else {}
        c = cls()
        c.enabled = str(s.get("enabled", "false")).strip().lower() == "true"
        c.max_agents = _int(s.get("max_agents", c.max_agents), 1, 32)
        c.user_max_cpu_fraction = _float(s.get("user_max_cpu_fraction", c.user_max_cpu_fraction), 0.1, 1.0)
        c.user_max_memory_fraction = _float(s.get("user_max_memory_fraction", c.user_max_memory_fraction), 0.1, 0.9)
        c.host_reserved_memory_mib = _int(s.get("host_reserved_memory_mib", c.host_reserved_memory_mib), 512, 1 << 20)
        b = s.get("default_backend", c.default_backend)
        c.default_backend = b if b in BACKENDS else "container"
        c.idle_exit_seconds = _int(s.get("idle_exit_seconds", c.idle_exit_seconds), 10, 3600)
        return c

    def save(self, path=None):
        path = path or CONF_PATH
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cp = configparser.ConfigParser()
        cp["agent-desktops"] = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in asdict(self).items()}
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("# Iron Agent Desktops - managed by Iron Settings / iron-agentd.\n")
            cp.write(f)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)


def _int(v, lo, hi):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        raise ConfigError(f"expected an integer, got {v!r}")


def _float(v, lo, hi):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        raise ConfigError(f"expected a number, got {v!r}")


# ---- host resources --------------------------------------------------------

@dataclass
class HostResources:
    threads: int
    memory_mib: int
    kvm: bool
    cgroup_v2: bool
    arch: str
    gpus: list = field(default_factory=list)
    render_nodes: list = field(default_factory=list)
    gpu_partitioning: str = "none"  # none | sriov | mig  (only reported when detected)

    @classmethod
    def detect(cls, hardware_json=HARDWARE_JSON):
        hw = {}
        try:
            with open(hardware_json, encoding="utf-8") as f:
                hw = json.load(f)
        except (OSError, ValueError):
            pass
        threads = hw.get("cpu", {}).get("threads") or os.cpu_count() or 1
        mem = hw.get("memory", {}).get("total_mib") or _meminfo_mib()
        return cls(
            threads=threads, memory_mib=mem,
            kvm=hw.get("kvm", os.path.exists("/dev/kvm")),
            cgroup_v2=hw.get("cgroup_v2", os.path.exists("/sys/fs/cgroup/cgroup.controllers")),
            arch=hw.get("arch", os.uname().machine),
            gpus=hw.get("gpus", []), render_nodes=hw.get("render_nodes", []),
            gpu_partitioning=_detect_gpu_partitioning(),
        )


def _meminfo_mib():
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            m = re.search(r"^MemTotal:\s*(\d+)", f.read(), re.M)
            return int(m.group(1)) // 1024 if m else 0
    except OSError:
        return 0


def _detect_gpu_partitioning():
    """Report hardware GPU partitioning only when the hardware actually exposes it."""
    try:
        for dev in os.listdir("/sys/bus/pci/devices"):
            base = f"/sys/bus/pci/devices/{dev}"
            if open(f"{base}/class").read().startswith("0x03") and os.path.exists(f"{base}/sriov_totalvfs"):
                if int(open(f"{base}/sriov_totalvfs").read().strip() or 0) > 0:
                    return "sriov"
    except OSError:
        pass
    return "none"


# ---- per-agent resources ------------------------------------------------------

@dataclass
class Resources:
    preset: str = "balanced"
    cpu_threads: int = 2          # threads the agent may run on (cpuset)
    cpu_quota_percent: int = 200  # CPU time cap; 100 = one full thread
    memory_mib: int = 4096        # hard limit (cgroup MemoryMax / guest RAM)
    storage_gib: int = 20         # size of the agent's private disk image
    gpu: str = "none"             # none | shared (render node access; no VRAM enforcement)
    network: str = "none"         # none | internet
    max_runtime_minutes: int = 0  # 0 = unlimited
    tasks_max: int = 4096


PRESETS = {
    # name: (cpu fraction, memory fraction, storage GiB, gpu, network)
    "light": (0.125, 0.125, 10, "none", "none"),
    "balanced": (0.25, 0.25, 20, "none", "internet"),
    "heavy": (0.5, 0.5, 40, "shared", "internet"),
}


def preset_resources(name, host):
    if name not in PRESETS:
        raise ConfigError(f"unknown preset {name!r}")
    cpu_f, mem_f, storage, gpu, net = PRESETS[name]
    threads = max(1, int(round(host.threads * cpu_f)))
    mem = max(1024, int(host.memory_mib * mem_f) // 256 * 256)
    if not host.render_nodes:
        gpu = "none"
    return Resources(preset=name, cpu_threads=threads, cpu_quota_percent=threads * 100,
                     memory_mib=mem, storage_gib=storage, gpu=gpu, network=net)


def validate_resources(r, host, gcfg, *, admin=False):
    """Clamp/validate a Resources object. Returns (resources, needs_admin: bool)."""
    if r.gpu not in GPU_MODES:
        raise ConfigError(f"gpu must be one of {GPU_MODES}")
    if r.network not in NETWORK_MODES:
        raise ConfigError(f"network must be one of {NETWORK_MODES}")
    if r.cpu_threads < 1 or r.cpu_threads > host.threads:
        raise ConfigError(f"cpu_threads must be 1..{host.threads}")
    if r.cpu_quota_percent < 10 or r.cpu_quota_percent > r.cpu_threads * 100:
        raise ConfigError(f"cpu_quota_percent must be 10..{r.cpu_threads * 100}")
    max_mem = host.memory_mib - gcfg.host_reserved_memory_mib
    if r.memory_mib < 512 or r.memory_mib > max_mem:
        raise ConfigError(f"memory_mib must be 512..{max_mem} (host keeps {gcfg.host_reserved_memory_mib} MiB)")
    if r.storage_gib < 4 or r.storage_gib > 2048:
        raise ConfigError("storage_gib must be 4..2048")
    if r.max_runtime_minutes < 0:
        raise ConfigError("max_runtime_minutes must be >= 0")
    if r.gpu == "shared" and not host.render_nodes:
        raise ConfigError("this computer exposes no GPU render node; GPU access is unavailable")
    needs_admin = (r.cpu_threads > host.threads * gcfg.user_max_cpu_fraction + 1e-9 or
                   r.memory_mib > host.memory_mib * gcfg.user_max_memory_fraction + 1e-9)
    return r, needs_admin and not admin


def total_allocation(agents):
    """Sum the resources of agents that currently hold them (running/paused)."""
    cpu = sum(a.resources.cpu_quota_percent for a in agents if a.state in ("running", "paused", "waiting", "starting"))
    mem = sum(a.resources.memory_mib for a in agents if a.state in ("running", "paused", "waiting", "starting"))
    return cpu, mem
