"""Agent Desktops page: feature toggle, agent list, creation and per-agent detail."""
import json
import os
import shutil

from gi.repository import Adw, Gio, GLib, Gtk

from .agentbus import AgentBus

STATE_LABEL = {"created": "Not started", "starting": "Starting…", "running": "Running", "paused": "Paused",
               "waiting": "Needs your approval", "stopped": "Stopped", "finished": "Finished", "failed": "Failed"}
LIVE = ("starting", "running", "paused", "waiting")
RUNTIMES = [("shell", "Desktop only"), ("claude-code", "Claude Code"), ("codex", "OpenAI Codex CLI"),
            ("agentdock", "AgentDock / AgentDock Pro")]
PRESETS = [("light", "Light"), ("balanced", "Balanced"), ("heavy", "Heavy"), ("custom", "Custom")]


def human_mib(m):
    return f"{m / 1024:.1f} GiB" if m >= 1024 else f"{m} MiB"


def summary(a):
    r = a["resources"]
    use = a.get("usage") or {}
    mem = f"{human_mib(use['memory_bytes'] >> 20)} of {human_mib(r['memory_mib'])}" if "memory_bytes" in use \
        else human_mib(r["memory_mib"])
    bits = [STATE_LABEL.get(a["state"], a["state"]), "VM" if a["backend"] == "vm" else "Container",
            f"{r['cpu_threads']} CPU", mem, f"{r['storage_gib']} GiB",
            "Internet" if r["network"] == "internet" else "No network"]
    if a.get("state_reason") and a["state"] in ("failed", "finished", "stopped"):
        bits.append(a["state_reason"])
    return " · ".join(bits)


class AgentsPage(Adw.Bin):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.bus = AgentBus()
        self.status = {}
        self.agents = []
        self.detail = None
        self.nav = Adw.NavigationView()
        self.set_child(self.nav)
        self.page = Adw.PreferencesPage(title="Agent Desktops", icon_name="computer-symbolic")
        self.nav.add(Adw.NavigationPage(child=self.page, title="Agent Desktops", tag="list"))

        intro = Adw.PreferencesGroup(
            title="Agent Desktops",
            description="Separate, isolated desktops where AI agents work with a share of this computer. "
                        "Agents run in containers or virtual machines with their own disk, limits and identity, "
                        "and cannot see your files unless you share a folder.")
        self.enable_row = Adw.SwitchRow(title="Agent Desktops", subtitle="Off — uses no resources")
        self._enable_handler = self.enable_row.connect("notify::active", self._on_toggle)
        intro.add(self.enable_row)
        self.host_row = Adw.ActionRow(title="This computer", subtitle="…")
        intro.add(self.host_row)
        self.image_row = Adw.ActionRow(title="Agent image", subtitle="…")
        self.image_btn = Gtk.Button(label="Prepare", valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
        self.image_btn.connect("clicked", self._prepare_image)
        self.image_row.add_suffix(self.image_btn)
        intro.add(self.image_row)
        self.page.add(intro)

        self.list_group = Adw.PreferencesGroup(title="Your agent desktops")
        new = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="New agent desktop",
                         css_classes=["flat"], valign=Gtk.Align.CENTER)
        new.connect("clicked", lambda *_: self._new_dialog())
        self.list_group.set_header_suffix(new)
        self.page.add(self.list_group)
        self._rows = []

        self.bus.subscribe("AgentChanged", lambda *_: self.refresh())
        self.bus.subscribe("ApprovalRequested", lambda *_: self.refresh())
        self.refresh()
        self._timer = GLib.timeout_add_seconds(5, self._tick)
        self.connect("destroy", lambda *_: (GLib.source_remove(self._timer), self.bus.close()))

    # ---- data --------------------------------------------------------------
    def _tick(self):
        if self.get_mapped() and (any(a["state"] in LIVE for a in self.agents) or self.detail):
            self.refresh()
        return GLib.SOURCE_CONTINUE

    def refresh(self):
        self.bus.call("GetStatus", on_done=self._got_status, on_error=self._status_error)

    def _status_error(self, msg):
        self.enable_row.set_sensitive(False)
        self.enable_row.set_subtitle(msg)

    def _got_status(self, st):
        self.status = st
        h = st["host"]
        with self.enable_row.handler_block(self._enable_handler):
            self.enable_row.set_active(st["enabled"])
        self.enable_row.set_sensitive(True)
        self.enable_row.set_subtitle(
            f"On — up to {st['max_agents']} at once, {st['live_agents']} running" if st["enabled"]
            else "Off — uses no resources")
        gpu = ", ".join(h["render_nodes"]) or "none"
        part = {"none": "no hardware GPU partitioning", "sriov": "SR-IOV GPU partitioning available"}.get(
            h["gpu_partitioning"], h["gpu_partitioning"])
        self.host_row.set_subtitle(f"{h['threads']} threads · {human_mib(h['memory_mib'])} · "
                                   f"{'KVM virtual machines' if h['kvm'] else 'no KVM (containers only)'} · "
                                   f"GPU: {gpu} ({part}; GPU memory is shared, not reserved)")
        imgs = st["images"]
        self.image_row.set_subtitle(
            ("Container image ready" if imgs["container"] else "Container image not prepared") + " · " +
            ("VM image ready" if imgs["vm"] else "VM image not prepared"))
        self.image_btn.set_label("Rebuild" if imgs["container"] else "Prepare")
        if imgs["container"]:
            self.image_btn.remove_css_class("suggested-action")
        else:
            self.image_btn.add_css_class("suggested-action")
        self.list_group.set_sensitive(st["enabled"])
        self.bus.call("ListAgents", on_done=self._got_agents, on_error=self.window.toast)

    def _got_agents(self, agents):
        self.agents = agents
        for r in self._rows:
            self.list_group.remove(r)
        self._rows = []
        if not agents:
            r = Adw.ActionRow(title="No agent desktops yet", subtitle="Create one with the + button")
            self.list_group.add(r)
            self._rows.append(r)
        for a in agents:
            r = Adw.ActionRow(title=a["name"], subtitle=summary(a), activatable=True)
            r.set_subtitle_lines(2)
            icon = "dialog-warning-symbolic" if a["state"] == "waiting" else (
                "media-playback-start-symbolic" if a["state"] in LIVE else "computer-symbolic")
            r.add_prefix(Gtk.Image(icon_name=icon))
            if a["state"] in ("running", "paused", "waiting"):
                b = Gtk.Button(label="Open", valign=Gtk.Align.CENTER)
                b.connect("clicked", lambda _b, i=a["id"]: self.open_desktop(i))
                r.add_suffix(b)
            if a["state"] in LIVE:
                b = Gtk.Button(icon_name="media-playback-stop-symbolic", valign=Gtk.Align.CENTER,
                               tooltip_text="Stop", css_classes=["flat"])
                b.connect("clicked", lambda _b, i=a["id"]: self.act("Stop", i))
            else:
                b = Gtk.Button(icon_name="media-playback-start-symbolic", valign=Gtk.Align.CENTER,
                               tooltip_text="Start", css_classes=["flat"])
                b.connect("clicked", lambda _b, i=a["id"]: self.act("Start", i))
            r.add_suffix(b)
            r.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            r.connect("activated", lambda _r, i=a["id"]: self.show_agent(i))
            self.list_group.add(r)
            self._rows.append(r)
        if self.detail:
            a = next((x for x in agents if x["id"] == self.detail.agent_id), None)
            if a:
                self.detail.update(a)

    # ---- actions -------------------------------------------------------------
    def act(self, method, agent_id, *extra, sig="s", ok=None):
        self.bus.call(method, sig, (agent_id, *extra), on_done=lambda *_: (ok and self.window.toast(ok), self.refresh()),
                      on_error=self.window.toast)

    def _on_toggle(self, row, _p):
        want = row.get_active()
        self.bus.call("SetEnabled", "b", (want,), on_done=lambda *_: self.refresh(),
                      on_error=lambda m: (self.window.toast(m), self.refresh()))

    def _prepare_image(self, _b):
        dlg = Adw.AlertDialog(heading="Prepare the agent image?",
                              body="Downloads a minimal Ubuntu system with a lightweight desktop for agents "
                                   "(about 1–2 GB, several minutes). Optional extras:")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        vm = Gtk.CheckButton(label="Also prepare virtual-machine agents", active=self.status.get("host", {}).get("kvm", False))
        claude = Gtk.CheckButton(label="Install Claude Code")
        codex = Gtk.CheckButton(label="Install OpenAI Codex CLI")
        browser = Gtk.CheckButton(label="Install Firefox for web research")
        for w in (vm, claude, codex, browser):
            box.append(w)
        dlg.set_extra_child(box)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("build", "Prepare")
        dlg.set_response_appearance("build", Adw.ResponseAppearance.SUGGESTED)

        def resp(_d, r):
            if r != "build":
                return
            argv = ["iron-agent", "image", "build"]
            if vm.get_active():
                argv.append("--vm")
            rts = [n for n, w in (("claude-code", claude), ("codex", codex)) if w.get_active()]
            if rts:
                argv += ["--runtime", ",".join(rts)]
            if browser.get_active():
                argv.append("--browser")
            self.window.run_privileged(argv, "Preparing the agent image", "Agent image ready.",
                                       on_finish=self.refresh)
        dlg.connect("response", resp)
        dlg.present(self.window)

    def open_desktop(self, agent_id):
        def got(d):
            if not d["available"]:
                self.window.toast("The agent desktop is still starting")
                return
            viewer = shutil.which("remote-viewer")
            if not viewer:
                self.window.toast("Install virt-viewer to open agent desktops")
                return
            Gio.Subprocess.new([viewer, "--title", "Agent Desktop", d["viewer_uri"]], Gio.SubprocessFlags.NONE)
        self.bus.call("GetDisplay", "s", (agent_id,), on_done=got, on_error=self.window.toast)

    def show_agent(self, agent_id, tab=None):
        a = next((x for x in self.agents if x["id"] == agent_id), None)
        if not a:
            self.bus.call("GetAgent", "s", (agent_id,), on_done=lambda x: self._push_detail(x, tab),
                          on_error=self.window.toast)
            return
        self._push_detail(a, tab)

    def _push_detail(self, a, tab=None):
        self.detail = AgentDetail(self, a)
        np = Adw.NavigationPage(child=self.detail, title=a["name"], tag="agent")
        np.connect("hidden", lambda *_: setattr(self, "detail", None))
        self.nav.push(np)
        if tab == "outputs":
            self.detail.focus_outputs()

    def _new_dialog(self):
        NewAgentDialog(self).present(self.window)


class NewAgentDialog(Adw.Dialog):
    def __init__(self, page):
        super().__init__(title="New agent desktop", content_width=520)
        self.page = page
        st = page.status
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        create = Gtk.Button(label="Create", css_classes=["suggested-action"])
        create.connect("clicked", self._create)
        hb.pack_start(cancel)
        hb.pack_end(create)
        tv.add_top_bar(hb)
        prefs = Adw.PreferencesPage()
        g = Adw.PreferencesGroup()
        self.name = Adw.EntryRow(title="Name", text="Agent Desktop")
        g.add(self.name)
        self.runtime = Adw.ComboRow(title="Agent", model=Gtk.StringList.new([lbl for _, lbl in RUNTIMES]))
        g.add(self.runtime)
        kvm = st.get("host", {}).get("kvm", False)
        self.backend = Adw.ComboRow(title="Isolation", model=Gtk.StringList.new(
            ["Container — light, fast to start", "Virtual machine — strongest isolation" + ("" if kvm else " (no KVM: slow)")]))
        g.add(self.backend)
        prefs.add(g)

        g = Adw.PreferencesGroup(title="Resources",
                                 description="Limits are enforced by the kernel. More than half of this computer "
                                             "needs an administrator's approval.")
        self.preset = Adw.ComboRow(title="Preset", model=Gtk.StringList.new([lbl for _, lbl in PRESETS]))
        self.preset.set_selected(1)
        g.add(self.preset)
        h = st.get("host", {"threads": 4, "memory_mib": 8192})
        self.cpus = self._spin("CPU threads", 1, h["threads"], 1)
        self.quota = self._spin("CPU time cap (%)", 10, h["threads"] * 100, 10)
        self.mem = self._spin("Memory (MiB)", 512, max(1024, h["memory_mib"] - 2048), 256)
        self.disk = self._spin("Storage (GiB)", 4, 512, 1)
        self.minutes = self._spin("Time limit (minutes, 0 = none)", 0, 10080, 15)
        for w in (self.cpus, self.quota, self.mem, self.disk, self.minutes):
            g.add(w)
        self.net = Adw.SwitchRow(title="Internet access", subtitle="Outbound only; cannot reach services on this computer")
        g.add(self.net)
        self.gpu = Adw.SwitchRow(title="GPU access", subtitle="Shared with the desktop; memory is not reserved")
        self.gpu.set_sensitive(bool(st.get("host", {}).get("render_nodes")))
        g.add(self.gpu)
        prefs.add(g)
        tv.set_content(prefs)
        self.set_child(tv)
        self.preset.connect("notify::selected", lambda *_: self._apply_preset())
        self._apply_preset()

    def _spin(self, title, lo, hi, step):
        r = Adw.SpinRow.new_with_range(lo, hi, step)
        r.set_title(title)
        r.connect("notify::value", lambda *_: self._mark_custom())
        return r

    def _mark_custom(self):
        if not getattr(self, "_applying", False) and self.preset.get_selected() != 3:
            self.preset.set_selected(3)

    def _apply_preset(self):
        key = PRESETS[self.preset.get_selected()][0]
        p = self.page.status.get("presets", {}).get(key)
        if not p:
            return
        self._applying = True
        self.cpus.set_value(p["cpu_threads"])
        self.quota.set_value(p["cpu_quota_percent"])
        self.mem.set_value(p["memory_mib"])
        self.disk.set_value(p["storage_gib"])
        self.net.set_active(p["network"] == "internet")
        self.gpu.set_active(p["gpu"] == "shared" and self.gpu.get_sensitive())
        self._applying = False

    def _create(self, _b):
        preset = PRESETS[self.preset.get_selected()][0]
        cfg = {"name": self.name.get_text().strip() or "Agent Desktop",
               "runtime": RUNTIMES[self.runtime.get_selected()][0],
               "backend": "vm" if self.backend.get_selected() == 1 else "container",
               "preset": "custom",
               "resources": {"preset": preset, "cpu_threads": int(self.cpus.get_value()),
                             "cpu_quota_percent": int(self.quota.get_value()),
                             "memory_mib": int(self.mem.get_value()), "storage_gib": int(self.disk.get_value()),
                             "max_runtime_minutes": int(self.minutes.get_value()),
                             "network": "internet" if self.net.get_active() else "none",
                             "gpu": "shared" if self.gpu.get_active() else "none"}}
        self.page.bus.call("CreateAgent", "s", (json.dumps(cfg),),
                           on_done=lambda i: (self.close(), self.page.refresh(), self.page.show_agent(i)),
                           on_error=self.page.window.toast)


class AgentDetail(Adw.Bin):
    def __init__(self, listpage, a):
        super().__init__()
        self.lp, self.bus, self.agent_id = listpage, listpage.bus, a["id"]
        self.page = Adw.PreferencesPage()
        self.set_child(self.page)

        g = Adw.PreferencesGroup()
        self.state_row = Adw.ActionRow(title="Status")
        self.state_row.set_subtitle_lines(3)
        g.add(self.state_row)
        self.buttons = Gtk.Box(spacing=8, margin_top=8, halign=Gtk.Align.START)
        g.add(self.buttons)
        self.page.add(g)

        g = Adw.PreferencesGroup(title="Desktop")
        self.preview = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, height_request=280, css_classes=["card"])
        g.add(self.preview)
        self.page.add(g)

        g = Adw.PreferencesGroup(title="Instructions", description="Runs with the agent's configured tool, visibly on its desktop.")
        self.instr = Adw.EntryRow(title="Tell the agent what to do", show_apply_button=True)
        self.instr.connect("apply", self._send)
        g.add(self.instr)
        self.page.add(g)

        self.approvals = Adw.PreferencesGroup(title="Waiting for your approval")
        self.page.add(self.approvals)
        self._approval_rows = []

        self.outputs = Adw.PreferencesGroup(title="Results", description="Files the agent placed in its outbox")
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", css_classes=["flat"])
        refresh.connect("clicked", lambda *_: self._load_outputs())
        self.outputs.set_header_suffix(refresh)
        self.page.add(self.outputs)
        self._output_rows = []

        self.shares = Adw.PreferencesGroup(title="Shared folders",
                                           description="Only these folders are visible to the agent. Revoking takes effect immediately.")
        add = Gtk.Button(icon_name="folder-new-symbolic", css_classes=["flat"], tooltip_text="Share a folder")
        add.connect("clicked", self._add_share)
        self.shares.set_header_suffix(add)
        self.page.add(self.shares)
        self._share_rows = []

        self.snaps = Adw.PreferencesGroup(title="Snapshots")
        snap = Gtk.Button(icon_name="camera-photo-symbolic", css_classes=["flat"], tooltip_text="Create snapshot")
        snap.connect("clicked", self._snapshot)
        self.snaps.set_header_suffix(snap)
        self.page.add(self.snaps)
        self._snap_rows = []

        g = Adw.PreferencesGroup()
        delete = Adw.ButtonRow(title="Delete agent desktop", css_classes=["destructive-action"])
        delete.connect("activated", self._delete)
        g.add(delete)
        self.page.add(g)
        self.update(a)
        self._load_outputs()

    def focus_outputs(self):
        GLib.idle_add(lambda: self.outputs.grab_focus() and False)

    def update(self, a):
        self.a = a
        self.state_row.set_subtitle(summary(a))
        child = self.buttons.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.buttons.remove(child)
            child = nxt

        def btn(label, cb, style=None):
            b = Gtk.Button(label=label)
            if style:
                b.add_css_class(style)
            b.connect("clicked", lambda *_: cb())
            self.buttons.append(b)
        live = a["state"] in LIVE
        if a["state"] in ("running", "paused", "waiting"):
            btn("Open desktop", lambda: self.lp.open_desktop(a["id"]), "suggested-action")
        if a["state"] in ("running", "waiting"):
            btn("Pause", lambda: self.lp.act("Pause", a["id"]))
        if a["state"] == "paused":
            btn("Resume", lambda: self.lp.act("Resume", a["id"]))
        if live:
            btn("Stop", lambda: self.lp.act("Stop", a["id"]))
        else:
            btn("Start", lambda: self.lp.act("Start", a["id"]), "suggested-action")
        self.instr.set_sensitive(a["state"] in ("running", "waiting"))
        if a["state"] in ("running", "waiting", "paused"):
            self.bus.call("GetPreview", "s", (a["id"],), parse=False,
                          on_done=lambda p: self.preview.set_filename(p), on_error=lambda *_: None)
        self._rebuild(self.shares, "_share_rows", [
            self._share_row(s) for s in a.get("shares", [])] or [Adw.ActionRow(title="No folders shared")])
        self._rebuild(self.snaps, "_snap_rows", [
            self._snap_row(s) for s in a.get("snapshots", [])] or [Adw.ActionRow(title="No snapshots")])
        self.bus.call("ListApprovals", on_done=self._got_approvals, on_error=lambda *_: None)

    def _rebuild(self, group, attr, rows):
        for r in getattr(self, attr):
            group.remove(r)
        for r in rows:
            group.add(r)
        setattr(self, attr, rows)

    def _got_approvals(self, reqs):
        rows = []
        for r in [x for x in reqs if x["agent_id"] == self.agent_id]:
            row = Adw.ActionRow(title=r["summary"], subtitle=r["detail"][:300] if r["detail"] != r["summary"] else "")
            row.set_subtitle_lines(4)
            for label, allow, style in (("Deny", False, "destructive-action"), ("Allow", True, "suggested-action")):
                b = Gtk.Button(label=label, valign=Gtk.Align.CENTER, css_classes=[style])
                b.connect("clicked", lambda _b, rid=r["id"], al=allow: self.lp.act("Decide", rid, al, sig="sb"))
                row.add_suffix(b)
            rows.append(row)
        self.approvals.set_visible(bool(rows))
        self._rebuild(self.approvals, "_approval_rows", rows)

    def _send(self, row):
        text = row.get_text().strip()
        if text:
            self.lp.act("SendInstruction", self.agent_id, text, sig="ss", ok="Instruction sent")
            row.set_text("")

    def _load_outputs(self):
        def got(files):
            rows = []
            for f in files[:200]:
                r = Adw.ActionRow(title=f["path"], subtitle=f"{f['size']:,} bytes")
                b = Gtk.Button(label="Export…", valign=Gtk.Align.CENTER)
                b.connect("clicked", lambda _b, p=f["path"]: self._export(p))
                r.add_suffix(b)
                rows.append(r)
            self._rebuild(self.outputs, "_output_rows", rows or [Adw.ActionRow(title="No results yet")])
        self.bus.call("ListOutputs", "s", (self.agent_id,), on_done=got, on_error=lambda *_: None)

    def _export(self, rel):
        dlg = Gtk.FileDialog(title="Export to folder", initial_folder=Gio.File.new_for_path(
            GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD) or os.path.expanduser("~")))

        def chosen(d, res):
            try:
                folder = d.select_folder_finish(res)
            except GLib.Error:
                return
            self.bus.call("ExportOutput", "sss", (self.agent_id, rel, folder.get_path()), parse=False,
                          on_done=lambda p: self.lp.window.toast(f"Exported to {p}"),
                          on_error=self.lp.window.toast)
        dlg.select_folder(self.lp.window, None, chosen)

    def _share_row(self, s):
        r = Adw.ActionRow(title=s["host_path"], subtitle=("Read and write" if s["writable"] else "Read only") +
                          f" · /home/agent/shared/{s['name']}")
        b = Gtk.Button(label="Revoke", valign=Gtk.Align.CENTER, css_classes=["destructive-action"])
        b.connect("clicked", lambda *_: self.lp.act("RevokeShare", self.agent_id, s["host_path"], sig="ss",
                                                    ok="Access revoked"))
        r.add_suffix(b)
        return r

    def _add_share(self, _b):
        dlg = Gtk.FileDialog(title="Share a folder with this agent")

        def chosen(d, res):
            try:
                folder = d.select_folder_finish(res)
            except GLib.Error:
                return
            ask = Adw.AlertDialog(heading="Allow the agent to change files?",
                                  body=f"{folder.get_path()}\n\nRead-only is safer. Changes apply the next time "
                                       "the agent starts.")
            ask.add_response("ro", "Read only")
            ask.add_response("rw", "Read and write")
            ask.set_response_appearance("rw", Adw.ResponseAppearance.DESTRUCTIVE)
            ask.connect("response", lambda _a, r: self.lp.act(
                "GrantShare", self.agent_id, folder.get_path(), r == "rw", sig="ssb", ok="Folder shared"))
            ask.present(self.lp.window)
        dlg.select_folder(self.lp.window, None, chosen)

    def _snap_row(self, s):
        when = GLib.DateTime.new_from_unix_local(int(s["created"])).format("%x %X")
        r = Adw.ActionRow(title=s["name"], subtitle=when)
        b = Gtk.Button(label="Restore", valign=Gtk.Align.CENTER)
        b.connect("clicked", lambda *_: self.lp.act("RestoreSnapshot", self.agent_id, s["name"], sig="ss",
                                                    ok="Snapshot restored"))
        r.add_suffix(b)
        return r

    def _snapshot(self, _b):
        name = GLib.DateTime.new_now_local().format("snap-%Y%m%d-%H%M%S")
        self.lp.act("CreateSnapshot", self.agent_id, name, sig="ss", ok=f"Snapshot {name} created")

    def _delete(self, _r):
        ask = Adw.AlertDialog(heading=f"Delete {self.a['name']}?",
                              body="Its disk, results and snapshots are removed permanently.")
        ask.add_response("cancel", "Cancel")
        ask.add_response("delete", "Delete")
        ask.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

        def resp(_d, r):
            if r == "delete":
                self.lp.act("DeleteAgent", self.agent_id, ok="Agent desktop deleted")
                self.lp.nav.pop()
        ask.connect("response", resp)
        ask.present(self.lp.window)
