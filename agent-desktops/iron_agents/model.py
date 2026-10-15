"""Agent records: persistence, ownership and the lifecycle state machine."""
import json
import os
import re
import secrets
import time
from dataclasses import asdict, dataclass, field

from .config import BACKENDS, STATE_DIR, ConfigError, Resources

STATES = ("created", "starting", "running", "paused", "waiting", "stopped", "finished", "failed")
# Allowed transitions (from -> set of to). "waiting" = blocked on a user approval.
TRANSITIONS = {
    "created": {"starting", "failed"},
    "starting": {"running", "failed", "stopped"},
    "running": {"paused", "waiting", "stopped", "finished", "failed"},
    "waiting": {"running", "paused", "stopped", "finished", "failed"},
    "paused": {"running", "waiting", "stopped", "finished", "failed"},
    "stopped": {"starting"},
    "finished": {"starting"},
    "failed": {"starting"},
}
NAME_RE = re.compile(r"^[\w .,:()'+-]{1,64}$")
SHARE_DEST_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class StateError(RuntimeError):
    pass


@dataclass
class Share:
    host_path: str
    writable: bool = False
    name: str = ""  # appears as /home/agent/shared/<name> inside the agent


@dataclass
class Agent:
    id: str
    name: str
    owner_uid: int
    backend: str = "container"
    runtime: str = "shell"  # see /usr/share/iron-agents/runtimes/*.json
    image: str = "base"
    resources: Resources = field(default_factory=Resources)
    shares: list = field(default_factory=list)  # [Share]
    state: str = "created"
    state_reason: str = ""
    created: float = field(default_factory=time.time)
    started: float = 0.0
    snapshots: list = field(default_factory=list)  # [{"name", "created"}]
    uid_base: int = 0  # container user-namespace base (assigned on first start)

    # ---- validation / serialization ------------------------------------
    def validate(self):
        if not NAME_RE.match(self.name or ""):
            raise ConfigError("agent name must be 1-64 printable characters")
        if self.backend not in BACKENDS:
            raise ConfigError(f"backend must be one of {BACKENDS}")
        if not re.fullmatch(r"[a-z0-9-]{1,32}", self.runtime):
            raise ConfigError("invalid runtime id")
        if not re.fullmatch(r"[a-z0-9-]{1,32}", self.image):
            raise ConfigError("invalid image id")
        names = set()
        for s in self.shares:
            if not SHARE_DEST_RE.match(s.name) or s.name in names:
                raise ConfigError(f"invalid or duplicate share name {s.name!r}")
            names.add(s.name)

    def to_dict(self, public=True):
        d = asdict(self)
        if public:
            d["live"] = self.state in ("running", "paused", "waiting", "starting")
        return d

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        d.pop("live", None)
        res = Resources(**{k: v for k, v in d.pop("resources", {}).items() if k in Resources.__dataclass_fields__})
        shares = [Share(**s) for s in d.pop("shares", [])]
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(resources=res, shares=shares, **known)

    def transition(self, new, reason=""):
        if new == self.state:
            return
        if new not in TRANSITIONS.get(self.state, set()):
            raise StateError(f"cannot go from {self.state} to {new}")
        self.state = new
        self.state_reason = reason
        if new == "starting":
            self.started = time.time()


def new_id():
    return "a" + secrets.token_hex(5)


class Store:
    """One directory per agent: <state>/<id>/agent.json plus its disk and data."""

    def __init__(self, root=STATE_DIR):
        self.root = root
        # Traversable but not listable: QEMU (iron-agent-vm) must reach VM agent
        # disks; each agent directory carries its own restrictive mode.
        os.makedirs(root, mode=0o711, exist_ok=True)
        os.chmod(root, 0o711)

    def path(self, agent_id, *parts):
        if not re.fullmatch(r"a[0-9a-f]{10}", agent_id or ""):
            raise ConfigError("invalid agent id")
        return os.path.join(self.root, agent_id, *parts)

    def load_all(self):
        agents = {}
        for d in sorted(os.listdir(self.root)):
            try:
                with open(os.path.join(self.root, d, "agent.json"), encoding="utf-8") as f:
                    a = Agent.from_dict(json.load(f))
                agents[a.id] = a
            except (OSError, ValueError, TypeError):
                continue
        return agents

    def save(self, agent):
        d = self.path(agent.id)
        os.makedirs(d, mode=0o700, exist_ok=True)
        tmp = os.path.join(d, ".agent.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(agent.to_dict(public=False), f, indent=2)
        os.replace(tmp, os.path.join(d, "agent.json"))

    def delete_dir(self, agent_id):
        d = self.path(agent_id)
        if os.path.isdir(d):
            # Never follow mounts out of the agent directory.
            if any(os.path.ismount(os.path.join(dp, x)) for dp, dirs, _ in os.walk(d) for x in dirs):
                raise StateError("agent storage is still mounted")
            import shutil
            shutil.rmtree(d)
