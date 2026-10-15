"""systemd transient units and cgroup v2 limits shared by both backends."""
import os
import subprocess

SLICE = "iron-agents.slice"


def unit_name(agent_id):
    return f"iron-agent-{agent_id}.service"


def cpuset(threads, host_threads, offset=0):
    """Pick `threads` CPUs counting down from the highest-numbered CPU, so agents
    leave CPU 0 (where most interrupts land) to the host desktop."""
    threads = max(1, min(threads, host_threads))
    start = max(0, host_threads - threads - offset)
    end = start + threads - 1
    return f"{start}-{end}" if end > start else str(start)


def cgroup_properties(res, host_threads, *, extra_memory_mib=0, gpu_devices=()):
    """systemd resource-control properties enforcing an agent's allocation."""
    props = [
        f"AllowedCPUs={cpuset(res.cpu_threads, host_threads)}",
        f"CPUQuota={res.cpu_quota_percent}%",
        f"MemoryMax={res.memory_mib + extra_memory_mib}M",
        f"MemoryHigh={int((res.memory_mib + extra_memory_mib) * 0.92)}M",
        "MemorySwapMax=0",
        f"TasksMax={res.tasks_max}",
        "IOWeight=50",
        "CPUWeight=50",
        "OOMPolicy=stop",
        "ManagedOOMMemoryPressure=kill",
    ]
    if res.max_runtime_minutes:
        props.append(f"RuntimeMaxSec={res.max_runtime_minutes * 60}")
    for dev in gpu_devices:
        props.append(f"DeviceAllow={dev} rw")
    return props


def systemd_run(agent_id, cmd, properties, *, description, notify=False):
    args = ["systemd-run", f"--unit={unit_name(agent_id)}", f"--slice={SLICE}",
            f"--description={description}", "--collect", "--quiet"]
    if notify:
        args.append("--service-type=notify")
    for p in properties:
        args.append(f"--property={p}")
    subprocess.run(args + ["--"] + cmd, check=True, capture_output=True, text=True)


def systemctl(*args, check=False):
    return subprocess.run(["systemctl", *args], check=check, capture_output=True, text=True)


def unit_state(agent_id):
    r = systemctl("show", unit_name(agent_id), "-p", "ActiveState", "-p", "SubState",
                  "-p", "FreezerState", "-p", "Result", "-p", "MainPID", "--value")
    vals = (r.stdout.strip().split("\n") + ["", "", "", "", ""])[:5]
    return dict(zip(("active", "sub", "freezer", "result", "pid"), vals))


def freeze(agent_id):
    systemctl("freeze", unit_name(agent_id), check=True)


def thaw(agent_id):
    systemctl("thaw", unit_name(agent_id), check=True)


def stop(agent_id):
    systemctl("stop", unit_name(agent_id))


def cgroup_path(agent_id):
    # systemd nests "iron-agents.slice" under "iron.slice".
    return f"/sys/fs/cgroup/iron.slice/{SLICE}/{unit_name(agent_id)}"


def usage(agent_id):
    """Live usage from cgroup v2 files: memory bytes and cumulative CPU usec."""
    base = cgroup_path(agent_id)
    out = {}
    try:
        out["memory_bytes"] = int(open(os.path.join(base, "memory.current")).read())
        for line in open(os.path.join(base, "cpu.stat")):
            k, v = line.split()
            if k == "usage_usec":
                out["cpu_usec"] = int(v)
        out["pids"] = int(open(os.path.join(base, "pids.current")).read())
    except (OSError, ValueError):
        pass
    return out
