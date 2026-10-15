"""iron-agentd: the org.ironlinux.AgentDesktops1 system service.

D-Bus activated, root, exits after a short idle period when no agent is live,
so a disabled or unused feature costs no memory or CPU.
"""
import json
import logging
import os
import pwd
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from gi.repository import Gio, GLib

from . import container, outputs, polkit, rfb, storage, units, vm
from .approvals import ApprovalQueue
from .config import ConfigError, GlobalConfig, HostResources, Resources, preset_resources, validate_resources
from .model import Agent, Share, StateError, Store, new_id

log = logging.getLogger("iron-agentd")
BUS_NAME = "org.ironlinux.AgentDesktops1"
OBJ_PATH = "/org/ironlinux/AgentDesktops1"
IFACE = "org.ironlinux.AgentDesktops1"
LIVE = ("starting", "running", "paused", "waiting")
INTROSPECTION = os.environ.get("IRON_AGENTS_IFACE", "/usr/share/dbus-1/interfaces/org.ironlinux.AgentDesktops1.xml")


class UserError(Exception):
    """Reported to the caller as org.ironlinux.AgentDesktops1.Error."""


def backend(agent):
    return container if agent.backend == "container" else vm


class Service:
    def __init__(self, loop):
        self.loop = loop
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=4)
        self.gcfg = GlobalConfig.load()
        self.host = HostResources.detect()
        self.store = Store()
        self.agents = self.store.load_all()
        self.approvals = ApprovalQueue()
        self.finished_seen = {}
        self.started = {}  # agent id -> (monotonic start time, hardware-accelerated)
        self.last_activity = time.monotonic()
        self.bus = None
        self._reconcile()

    # ---- bus plumbing ------------------------------------------------------
    def register(self, bus):
        self.bus = bus
        with open(INTROSPECTION, encoding="utf-8") as f:
            node = Gio.DBusNodeInfo.new_for_xml(f.read())
        bus.register_object(OBJ_PATH, node.interfaces[0], self._on_call, None, None)
        GLib.timeout_add_seconds(2, self._tick)

    def _on_call(self, bus, sender, path, iface, method, params, invocation):
        self.last_activity = time.monotonic()
        handler = getattr(self, f"m_{method}", None)
        if handler is None:
            invocation.return_dbus_error(f"{IFACE}.Error", f"unknown method {method}")
            return
        try:
            with self.lock:
                result = handler(sender, *params.unpack())
            out_sig = "".join(a.signature for a in invocation.get_method_info().out_args)
            invocation.return_value(GLib.Variant(f"({out_sig})", (result,)) if out_sig else None)
        except polkit.NotAuthorized as e:
            invocation.return_dbus_error(f"{IFACE}.NotAuthorized", str(e))
        except (UserError, ConfigError, StateError, KeyError, ValueError, PermissionError) as e:
            invocation.return_dbus_error(f"{IFACE}.Error", str(e).strip("'\""))
        except Exception as e:  # noqa: BLE001 - report, don't crash the service
            log.exception("method %s failed", method)
            invocation.return_dbus_error(f"{IFACE}.Error", f"internal error: {e}")

    def emit(self, signal, *args):
        """Emit from the main loop (callers may be worker threads)."""
        if not self.bus:
            return

        def send():
            self.bus.emit_signal(None, OBJ_PATH, IFACE, signal, GLib.Variant(f"({'s' * len(args)})", args))
            return GLib.SOURCE_REMOVE
        GLib.idle_add(send)

    # ---- helpers -----------------------------------------------------------
    def _uid(self, sender):
        return polkit.caller_uid(self.bus, sender)

    def _agent_for(self, sender, agent_id):
        a = self.agents.get(agent_id)
        if not a:
            raise UserError("no such agent")
        if self._uid(sender) != a.owner_uid:
            polkit.check(self.bus, sender, polkit.MANAGE_ALL)
        return a

    def _require_enabled(self):
        if not self.gcfg.enabled:
            raise UserError("Agent Desktops are turned off (Iron Settings → Agent Desktops)")

    def _save(self, a, state=None, reason=""):
        if state:
            a.transition(state, reason)
        self.store.save(a)
        self.emit("AgentChanged", a.id, a.state)

    def _run_dir(self, a):
        return backend(a).run_dir(a)

    def _reconcile(self):
        """After a restart: agents marked live whose unit is gone become stopped."""
        for a in self.agents.values():
            if a.state in LIVE and units.unit_state(a.id)["active"] not in ("active", "activating", "reloading"):
                a.state, a.state_reason = "stopped", "service restarted"
                self.store.save(a)

    # ---- methods -------------------------------------------------------------
    def m_GetStatus(self, sender):
        live = [a for a in self.agents.values() if a.state in LIVE]
        return json.dumps({
            "enabled": self.gcfg.enabled,
            "max_agents": self.gcfg.max_agents,
            "live_agents": len(live),
            "host": self.host.__dict__,
            "limits": {"user_max_cpu_fraction": self.gcfg.user_max_cpu_fraction,
                       "user_max_memory_fraction": self.gcfg.user_max_memory_fraction,
                       "host_reserved_memory_mib": self.gcfg.host_reserved_memory_mib},
            "images": {b: storage.image_ready("base", b) for b in ("container", "vm")},
            "presets": {p: preset_resources(p, self.host).__dict__ for p in ("light", "balanced", "heavy")},
        })

    def m_SetEnabled(self, sender, enabled):
        polkit.check(self.bus, sender, polkit.CONFIGURE)
        self.gcfg.enabled = bool(enabled)
        self.gcfg.save()
        if not enabled:
            for a in list(self.agents.values()):
                if a.state in LIVE:
                    self._stop_async(a, "Agent Desktops turned off")
        return None

    def m_ListAgents(self, sender):
        uid = self._uid(sender)
        see_all = uid == 0 or polkit.is_authorized(self.bus, sender, polkit.MANAGE_ALL)
        return json.dumps([self._public(a) for a in self.agents.values() if see_all or a.owner_uid == uid])

    def _public(self, a):
        d = a.to_dict()
        d["usage"] = units.usage(a.id) if a.state in LIVE else {}
        d["pending_approvals"] = len(self.approvals.for_agent(a.id))
        if a.state in LIVE:
            # What the in-agent runner reports (task number/state/summary); absent
            # until the guest is up, which for VM agents means it is still booting.
            d["task"] = self._runner_status(a)
            d["guest_ready"] = d["task"] is not None
        return d

    def _runner_status(self, a):
        try:
            with open(os.path.join(self._run_dir(a), "control", "status.json"), encoding="utf-8") as f:
                st = json.loads(f.read(8192))
        except (OSError, ValueError):
            return None
        return {k: st.get(k) for k in ("task", "state", "summary", "updated")}

    def m_GetAgent(self, sender, agent_id):
        return json.dumps(self._public(self._agent_for(sender, agent_id)))

    def _parse_config(self, sender, cfg_json, agent=None):
        try:
            cfg = json.loads(cfg_json)
        except ValueError:
            raise UserError("configuration must be JSON")
        a = agent or Agent(id=new_id(), name="Agent", owner_uid=self._uid(sender),
                           backend=self.gcfg.default_backend)
        for k in ("name", "runtime", "backend", "image"):
            if k in cfg:
                setattr(a, k, str(cfg[k]))
        if "preset" in cfg and cfg["preset"] != "custom":
            a.resources = preset_resources(cfg["preset"], self.host)
        if "resources" in cfg:
            fields = Resources.__dataclass_fields__
            merged = {**a.resources.__dict__, **{k: v for k, v in cfg["resources"].items() if k in fields}}
            for k in ("cpu_threads", "cpu_quota_percent", "memory_mib", "storage_gib", "max_runtime_minutes", "tasks_max"):
                merged[k] = int(merged[k])
            a.resources = Resources(**merged)
            if cfg.get("preset", "custom") == "custom":
                a.resources.preset = "custom"
        a.validate()
        _, needs_admin = validate_resources(a.resources, self.host, self.gcfg)
        if needs_admin:
            polkit.check(self.bus, sender, polkit.ALLOCATE_HIGH)
        return a

    def m_CreateAgent(self, sender, cfg_json):
        polkit.check(self.bus, sender, polkit.USE)
        self._require_enabled()
        mine = [a for a in self.agents.values() if a.owner_uid == self._uid(sender)]
        if len(mine) >= 16:
            raise UserError("you already have 16 agent desktops; delete one first")
        a = self._parse_config(sender, cfg_json)
        self.agents[a.id] = a
        self._save(a)
        return a.id

    def m_UpdateAgent(self, sender, agent_id, cfg_json):
        a = self._agent_for(sender, agent_id)
        if a.state in LIVE:
            raise UserError("stop the agent before changing its configuration")
        old_storage = a.resources.storage_gib
        self._parse_config(sender, cfg_json, agent=a)
        if a.resources.storage_gib < old_storage:
            a.resources.storage_gib = old_storage
            raise UserError("agent storage can grow but not shrink")
        self._save(a)

    def m_DeleteAgent(self, sender, agent_id):
        a = self._agent_for(sender, agent_id)
        if a.state in LIVE:
            raise UserError("stop the agent first")
        self.store.delete_dir(a.id)
        del self.agents[a.id]
        self.approvals.drop_agent(a.id)
        self.emit("AgentChanged", a.id, "deleted")

    def m_Start(self, sender, agent_id):
        a = self._agent_for(sender, agent_id)
        self._require_enabled()
        if a.state in LIVE:
            return None
        live = [x for x in self.agents.values() if x.state in LIVE]
        if len(live) >= self.gcfg.max_agents:
            raise UserError(f"at most {self.gcfg.max_agents} agent desktops can run at once")
        mem_budget = self.host.memory_mib - self.gcfg.host_reserved_memory_mib
        used = sum(x.resources.memory_mib for x in live)
        if used + a.resources.memory_mib > mem_budget:
            raise UserError(f"not enough memory: running agents hold {used} MiB of the {mem_budget} MiB agent budget")
        if not storage.image_ready(a.image, a.backend):
            raise UserError("the agent base image is not installed yet (Iron Settings → Agent Desktops → Prepare image)")
        if a.backend == "container":
            a.uid_base = container.allocate_uid_base(a, [x for x in self.agents.values() if x.id != a.id])
        self._save(a, "starting")
        self.pool.submit(self._start_worker, a)

    def _start_worker(self, a):
        try:
            # A status file left from the previous run must not look like a live guest.
            try:
                os.unlink(os.path.join(self._run_dir(a), "control", "status.json"))
            except OSError:
                pass
            info = backend(a).start(self.store, a, self.host) or {}
            with self.lock:
                self.started[a.id] = (time.monotonic(), info.get("kvm", True))
                self._save(a, "running")
        except Exception as e:  # noqa: BLE001
            log.exception("start %s failed", a.id)
            units.stop(a.id)
            with self.lock:
                self._save(a, "failed", str(getattr(e, "stderr", "") or e)[-500:])

    def _stop_async(self, a, reason=""):
        def work():
            try:
                backend(a).stop(a)
            finally:
                with self.lock:
                    if a.state in LIVE:
                        self._save(a, "stopped", reason)
                    self.approvals.drop_agent(a.id)
        self.pool.submit(work)

    def m_Stop(self, sender, agent_id):
        a = self._agent_for(sender, agent_id)
        if a.state in LIVE:
            if a.state == "paused":
                backend(a).resume(a)
            self._stop_async(a, "stopped by user")

    def m_Pause(self, sender, agent_id):
        a = self._agent_for(sender, agent_id)
        if a.state not in ("running", "waiting"):
            raise UserError("agent is not running")
        backend(a).pause(a)
        self._save(a, "paused")

    def m_Resume(self, sender, agent_id):
        a = self._agent_for(sender, agent_id)
        if a.state != "paused":
            raise UserError("agent is not paused")
        backend(a).resume(a)
        self._save(a, "waiting" if self.approvals.for_agent(a.id) else "running")

    def m_SendInstruction(self, sender, agent_id, text):
        a = self._agent_for(sender, agent_id)
        if a.state not in ("running", "waiting"):
            raise UserError("start the agent before sending instructions")
        if not text.strip() or len(text) > 32768:
            raise UserError("instruction must be 1..32768 characters")
        inbox = os.path.join(self._run_dir(a), "control", "inbox")
        name = f"{time.time_ns()}.json"
        tmp = os.path.join(inbox, "." + name)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"type": "instruction", "text": text, "from_uid": self._uid(sender)}, f)
        owner = a.uid_base if a.backend == "container" else vm._vm_ids()[0]
        os.chown(tmp, owner, owner)
        os.chmod(tmp, 0o640)
        os.replace(tmp, os.path.join(inbox, name))

    def m_GetDisplay(self, sender, agent_id):
        a = self._agent_for(sender, agent_id)
        sock = os.path.join(self._run_dir(a), "display", "vnc.sock")
        if a.backend == "vm" and a.state in LIVE:
            vm.share_display(a)
        return json.dumps({"vnc_socket": sock, "available": os.path.exists(sock),
                           "viewer_uri": f"vnc+unix://{sock}"})

    def m_GetPreview(self, sender, agent_id):
        a = self._agent_for(sender, agent_id)
        if a.state not in LIVE:
            raise UserError("agent is not running")
        rd = self._run_dir(a)
        png = os.path.join(rd, "preview.png")
        try:
            rfb.grab_png(os.path.join(rd, "display", "vnc.sock"), png)
        except (OSError, rfb.RFBError) as e:
            raise UserError(f"desktop not available yet: {e}")
        os.chown(png, a.owner_uid, -1)
        os.chmod(png, 0o600)
        return png

    def m_GrantShare(self, sender, agent_id, host_path, writable):
        a = self._agent_for(sender, agent_id)
        if a.backend != "container":
            raise UserError("shared folders are supported for container agents")
        home = pwd.getpwuid(a.owner_uid).pw_dir
        real = container.validate_share_path(host_path, a.owner_uid, home)
        name = os.path.basename(real)[:48] or "share"
        existing = {s.name for s in a.shares if s.host_path != real}
        base, n = name, 2
        while name in existing:
            name, n = f"{base}-{n}", n + 1
        a.shares = [s for s in a.shares if s.host_path != real] + [Share(real, bool(writable), name)]
        a.validate()
        self._save(a)

    def m_RevokeShare(self, sender, agent_id, host_path):
        a = self._agent_for(sender, agent_id)
        real = os.path.realpath(host_path)
        gone = [s for s in a.shares if s.host_path == real]
        if not gone:
            raise UserError("that folder is not shared with this agent")
        a.shares = [s for s in a.shares if s.host_path != real]
        if a.state in LIVE and a.backend == "container":
            for s in gone:
                container.revoke_share_live(a, s.name)
        self._save(a)

    def _guest_root(self, a):
        if a.backend != "container":
            return None
        return container.guest_root(a) if a.state in LIVE else None

    def m_ListOutputs(self, sender, agent_id):
        a = self._agent_for(sender, agent_id)
        if a.backend == "vm":
            # VM agents publish into the 9p control share (guest: /home/agent/outbox).
            return json.dumps(outputs.list_outputs(self._run_dir(a), outbox="control/outbox"))
        root = self._guest_root(a)
        if root:
            return json.dumps(outputs.list_outputs(root))
        disk = self.store.path(a.id, "disk.img")
        if not os.path.exists(disk):
            return "[]"
        with storage.ReadOnlyMount(disk, self.store.path(a.id, "mnt-review")) as mnt:
            return json.dumps(outputs.list_outputs(mnt))

    def m_ExportOutput(self, sender, agent_id, rel_path, dest_dir):
        a = self._agent_for(sender, agent_id)
        uid = self._uid(sender)
        gid = pwd.getpwuid(uid).pw_gid
        if a.backend == "vm":
            return outputs.export(self._run_dir(a), rel_path, dest_dir, uid, gid, outbox="control/outbox")
        root = self._guest_root(a)
        if root:
            return outputs.export(root, rel_path, dest_dir, uid, gid)
        with storage.ReadOnlyMount(self.store.path(a.id, "disk.img"), self.store.path(a.id, "mnt-review")) as mnt:
            return outputs.export(mnt, rel_path, dest_dir, uid, gid)

    def m_ListApprovals(self, sender):
        uid = self._uid(sender)
        return json.dumps([r for r in self.approvals.pending.values()
                           if self.agents.get(r["agent_id"]) and self.agents[r["agent_id"]].owner_uid == uid])

    def m_Decide(self, sender, request_id, allow):
        req = self.approvals.pending.get(request_id)
        if not req:
            raise UserError("no such pending request")
        a = self._agent_for(sender, req["agent_id"])
        owner = a.uid_base if a.backend == "container" else vm._vm_ids()[0]
        self.approvals.decide(request_id, allow, os.path.join(self._run_dir(a), "control"), owner,
                              virtfs_root=a.backend == "vm")
        if a.state == "waiting" and not self.approvals.for_agent(a.id):
            self._save(a, "running")

    def m_CreateSnapshot(self, sender, agent_id, name):
        a = self._agent_for(sender, agent_id)
        if not name or not all(c.isalnum() or c in "-_" for c in name) or len(name) > 40:
            raise UserError("snapshot names use letters, digits, - and _")
        backend(a).snapshot(self.store, a, name)
        a.snapshots = [s for s in a.snapshots if s["name"] != name] + [{"name": name, "created": time.time()}]
        self._save(a)

    def m_RestoreSnapshot(self, sender, agent_id, name):
        a = self._agent_for(sender, agent_id)
        if name not in {s["name"] for s in a.snapshots}:
            raise UserError("no such snapshot")
        backend(a).restore(self.store, a, name)
        self._save(a)

    # ---- periodic work -------------------------------------------------------
    def _tick(self):
        with self.lock:
            live = [a for a in self.agents.values() if a.state in LIVE]
            for a in live:
                if a.state == "starting":
                    continue
                st = units.unit_state(a.id)
                if st["active"] not in ("active", "activating", "deactivating", "reloading"):
                    reason = {"timeout": "time limit reached", "oom-kill": "memory limit exceeded"}.get(st["result"], "")
                    self._save(a, "finished" if st["result"] in ("success", "timeout") else "failed",
                               reason or f"exited ({st['result'] or 'unknown'})")
                    self.approvals.drop_agent(a.id)
                    continue
                ctl = os.path.join(self._run_dir(a), "control")
                for req in self.approvals.scan(a, ctl):
                    self.emit("ApprovalRequested", json.dumps(req))
                    if a.state == "running":
                        self._save(a, "waiting")
                self._check_finished(a, ctl)
                self._check_guest_boot(a, ctl)
            idle_for = time.monotonic() - self.last_activity
            if not live and idle_for > self.gcfg.idle_exit_seconds:
                log.info("idle; exiting")
                self.loop.quit()
                return False
        return True

    def _check_guest_boot(self, a, ctl):
        """Tell the owner when a VM guest never comes up, with its console output."""
        if a.backend != "vm" or a.id not in self.started or os.path.exists(os.path.join(ctl, "status.json")):
            return
        t0, kvm = self.started[a.id]
        limit = 240 if kvm else 1500
        waited = time.monotonic() - t0
        if waited > limit and not a.state_reason.startswith("guest not ready"):
            tail = [l for l in vm.guest_console_log(a).splitlines() if l.strip()][-3:]
            a.state_reason = (f"guest not ready after {int(waited)} s"
                              + (": " + " | ".join(t.strip()[:160] for t in tail) if tail else ""))
            self._save(a)

    def _check_finished(self, a, ctl):
        """The in-agent runner writes status.json {"task": n, "state": "done", "summary": ...}."""
        try:
            with open(os.path.join(ctl, "status.json"), encoding="utf-8") as f:
                st = json.loads(f.read(8192))
        except (OSError, ValueError):
            return
        key = (st.get("task"), st.get("state"))
        if st.get("state") in ("done", "failed") and self.finished_seen.get(a.id) != key:
            self.finished_seen[a.id] = key
            prefix = "" if st["state"] == "done" else "FAILED: "
            self.emit("AgentFinished", a.id, (prefix + str(st.get("summary", "")))[:300])


def main():
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    loop = GLib.MainLoop()
    svc = Service(loop)

    def on_bus(bus, _name):
        svc.register(bus)

    Gio.bus_own_name(Gio.BusType.SYSTEM, BUS_NAME, Gio.BusNameOwnerFlags.NONE,
                     on_bus, None, lambda *_: loop.quit())
    loop.run()
    svc.pool.shutdown(wait=True)
