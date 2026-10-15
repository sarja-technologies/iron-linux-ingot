"""Approval gates between an agent and its owner.

Inside the agent, `iron-approve` writes requests/<rid>.json into the shared
control directory and blocks until responses/<rid>.json appears. The daemon
watches running agents' request directories, announces new requests over
D-Bus, and writes the owner's decision. Requests are untrusted agent input:
they are size-limited, schema-checked and never executed by the host.
"""
import hashlib
import json
import os
import re
import shlex
import time

MAX_REQUEST_BYTES = 16384
RID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
KINDS = ("tool", "elevate", "network", "message")


class ApprovalQueue:
    def __init__(self):
        self.pending = {}  # request_id -> request dict (with agent_id)
        self.seen = set()

    def scan(self, agent, control_dir):
        """Return newly discovered, valid requests for one agent."""
        req_dir = os.path.join(control_dir, "requests")
        new = []
        try:
            names = os.listdir(req_dir)
        except OSError:
            return new
        for fn in names:
            if not fn.endswith(".json"):
                continue
            rid = fn[:-5]
            key = f"{agent.id}:{rid}"
            if key in self.seen or not RID_RE.match(rid):
                continue
            self.seen.add(key)
            path = os.path.join(req_dir, fn)
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, "rb") as f:
                    if not os.path.isfile(path) or os.fstat(f.fileno()).st_size > MAX_REQUEST_BYTES:
                        continue
                    data = f.read()
                    raw = json.loads(data.decode("utf-8", "replace"))
            except (OSError, ValueError):
                continue
            kind = raw.get("kind") if raw.get("kind") in KINDS else "message"
            if kind == "elevate":
                # Never show agent-written prose for root commands: derive it from argv.
                argv = raw.get("argv")
                if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
                    continue
                raw["summary"] = "Run as root inside the agent: " + shlex.join(argv)[:400]
                raw["detail"] = shlex.join(argv)
            req = {
                "id": f"{agent.id}-{rid}",
                "rid": rid,
                "agent_id": agent.id,
                "agent_name": agent.name,
                "kind": kind,
                "summary": str(raw.get("summary", ""))[:500],
                "detail": str(raw.get("detail", ""))[:4000],
                "created": time.time(),
                # Binds the decision to exactly what the owner was shown.
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            self.pending[req["id"]] = req
            new.append(req)
        return new

    def decide(self, request_id, allow, control_dir, uid_owner_of_dir=None):
        req = self.pending.pop(request_id, None)
        if not req:
            raise KeyError("no such pending request")
        resp_dir = os.path.join(control_dir, "responses")
        tmp = os.path.join(resp_dir, f".{req['rid']}.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"allow": bool(allow), "decided": time.time(), "request_sha256": req["sha256"]}, f)
        if uid_owner_of_dir is not None:
            os.chown(tmp, uid_owner_of_dir, uid_owner_of_dir)
        os.chmod(tmp, 0o644)
        os.replace(tmp, os.path.join(resp_dir, f"{req['rid']}.json"))
        return req

    def for_agent(self, agent_id):
        return [r for r in self.pending.values() if r["agent_id"] == agent_id]

    def drop_agent(self, agent_id):
        for k in [k for k, r in self.pending.items() if r["agent_id"] == agent_id]:
            del self.pending[k]
        self.seen = {s for s in self.seen if not s.startswith(agent_id + ":")}
