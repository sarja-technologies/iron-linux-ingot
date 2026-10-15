"""Iron Settings pages: Appearance, Tiling, Hardware & Drivers, Updates, About."""
import json
import os
import shutil
import subprocess
import threading

from gi.repository import Adw, Gio, GLib, Gtk


def schema_settings(schema_id):
    src = Gio.SettingsSchemaSource.get_default()
    if src and src.lookup(schema_id, True):
        return Gio.Settings.new(schema_id)
    return None


def spawn(argv):
    try:
        Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE)
        return True
    except GLib.Error:
        return False


def os_release():
    d = {}
    try:
        with open("/etc/os-release") as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                d[k] = v.strip('"')
    except OSError:
        pass
    return d


def hardware():
    try:
        with open("/run/iron/hardware.json") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def switch_row(title, subtitle, settings, key):
    row = Adw.SwitchRow(title=title, subtitle=subtitle or "")
    if settings:
        settings.bind(key, row, "active", Gio.SettingsBindFlags.DEFAULT)
    else:
        row.set_sensitive(False)
    return row


def combo_row(title, subtitle, settings, key, choices):
    """choices: [(value, label)]"""
    row = Adw.ComboRow(title=title, subtitle=subtitle or "")
    row.set_model(Gtk.StringList.new([lbl for _, lbl in choices]))
    if not settings:
        row.set_sensitive(False)
        return row
    values = [v for v, _ in choices]
    cur = settings.get_string(key)
    row.set_selected(values.index(cur) if cur in values else 0)
    row.connect("notify::selected", lambda r, _p: settings.set_string(key, values[r.get_selected()]))
    return row


def spin_row(title, subtitle, settings, key, lo, hi, step=1):
    row = Adw.SpinRow.new_with_range(lo, hi, step)
    row.set_title(title)
    row.set_subtitle(subtitle or "")
    if settings:
        settings.bind(key, row, "value", Gio.SettingsBindFlags.DEFAULT)
    else:
        row.set_sensitive(False)
    return row


# ---- Appearance ----------------------------------------------------------------

WALLPAPERS = [("ingot-dawn", "Dawn"), ("ingot-steel", "Steel"), ("ingot-forge", "Forge")]
ACCENTS = [("blue", "Cobalt"), ("slate", "Steel"), ("teal", "Teal"), ("green", "Green"),
           ("yellow", "Amber"), ("orange", "Forge"), ("red", "Red"), ("pink", "Rose")]


def appearance_page():
    page = Adw.PreferencesPage(title="Appearance", icon_name="preferences-desktop-appearance-symbolic")
    iface = schema_settings("org.gnome.desktop.interface")
    bg = schema_settings("org.gnome.desktop.background")

    g = Adw.PreferencesGroup(title="Style")
    g.add(combo_row("Style", "Applies to apps and the shell", iface, "color-scheme",
                    [("prefer-dark", "Dark"), ("default", "Light"), ("prefer-light", "Light (explicit)")]))
    if iface and "accent-color" in iface.list_keys():
        g.add(combo_row("Accent colour", None, iface, "accent-color", ACCENTS))
    g.add(switch_row("Animations", "Turn off for slower graphics or less motion", iface, "enable-animations"))
    page.add(g)

    g = Adw.PreferencesGroup(title="Wallpaper", description="Original Iron Linux artwork")
    flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3, column_spacing=12,
                       row_spacing=12, homogeneous=True)
    for wid, label in WALLPAPERS:
        path = f"/usr/share/backgrounds/iron/{wid}.jpg"
        btn = Gtk.Button(tooltip_text=label, css_classes=["flat", "iron-wallpaper"])
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        if os.path.exists(path):
            pic = Gtk.Picture.new_for_filename(path)
            pic.set_content_fit(Gtk.ContentFit.COVER)
            pic.set_size_request(180, 100)
            box.append(pic)
        box.append(Gtk.Label(label=label))
        btn.set_child(box)

        def set_wp(_b, p=path):
            if bg:
                uri = GLib.filename_to_uri(p)
                bg.set_string("picture-uri", uri)
                bg.set_string("picture-uri-dark", uri)
        btn.connect("clicked", set_wp)
        flow.append(btn)
    g.add(flow)
    more = Adw.ButtonRow(title="More backgrounds in GNOME Settings…")
    more.connect("activated", lambda *_: spawn(["gnome-control-center", "background"]))
    g.add(more)
    page.add(g)

    if os.path.isdir("/usr/share/gnome-shell/extensions/gnotch@gnotch.dev"):
        shell = schema_settings("org.gnome.shell")
        g = Adw.PreferencesGroup(title="Gnotch",
                                 description="An expandable notch in the top bar with addons such as Voice Notes "
                                             "and Agent Workspace. Takes effect after logging out and in.")
        row = Adw.SwitchRow(title="Show Gnotch")
        uuid = "gnotch@gnotch.dev"
        row.set_active(uuid in shell.get_strv("enabled-extensions"))

        def toggle(r, _p):
            exts = [e for e in shell.get_strv("enabled-extensions") if e != uuid]
            shell.set_strv("enabled-extensions", exts + ([uuid] if r.get_active() else []))
        row.connect("notify::active", toggle)
        g.add(row)
        page.add(g)

    dock = schema_settings("org.gnome.shell.extensions.dash-to-dock")
    g = Adw.PreferencesGroup(title="Taskbar", description="The Ingot dock")
    g.add(combo_row("Position", None, dock, "dock-position",
                    [("BOTTOM", "Bottom"), ("LEFT", "Left"), ("RIGHT", "Right")]))
    g.add(switch_row("Hide automatically", "Show the dock when no window overlaps it", dock, "intellihide"))
    g.add(switch_row("Auto-hide", "Reveal on pointer at the screen edge", dock, "autohide"))
    g.add(spin_row("Icon size", None, dock, "dash-max-icon-size", 24, 64, 4))
    page.add(g)
    return page


# ---- Tiling ----------------------------------------------------------------------

LAYOUT_CHOICES = [("none", "Floating (no tiling)"), ("columns-2", "Two columns"), ("columns-3", "Three columns"),
                  ("grid-2x2", "2 × 2 grid"), ("grid-3x3", "3 × 3 grid")]
SHORTCUTS = [("Super+Alt+1 … 4", "Two columns, three columns, 2×2, 3×3 on this workspace"),
             ("Super+Alt+0", "Turn tiling off on this workspace"),
             ("Super+Alt+Space", "Cycle layouts"),
             ("Super+Alt+Arrows", "Swap the window with its neighbour"),
             ("Super+Alt+F", "Float or re-tile the focused window"),
             ("Drag + Ctrl", "Show snap zones while moving a window")]


def tiling_page():
    page = Adw.PreferencesPage(title="Tiling", icon_name="view-grid-symbolic")
    s = schema_settings("org.ironlinux.tiling")
    if not s:
        page.add(Adw.PreferencesGroup(title="Iron Tiling is not installed",
                                      description="Install the iron-shell package."))
        return page
    g = Adw.PreferencesGroup(title="Layouts",
                             description="Each workspace on each monitor keeps its own layout and tile sizes.")
    g.add(combo_row("Default layout", "For workspaces you have not set a layout on", s, "default-layout",
                    LAYOUT_CHOICES))
    g.add(combo_row("Snap zones", "Shown while dragging a window with the snap key held", s, "snap-layout",
                    LAYOUT_CHOICES[1:]))
    reset = Adw.ButtonRow(title="Reset all workspace layouts")
    reset.connect("activated", lambda *_: s.set_string("workspace-layouts", "{}"))
    g.add(reset)
    page.add(g)

    g = Adw.PreferencesGroup(title="Snapping")
    g.add(switch_row("Drag to snap", "Snap zones and screen-edge snapping", s, "enabled"))
    g.add(switch_row("Snap at screen edges", "Halves at the sides, quarters at the corners, maximise at the top",
                     s, "edge-snap"))
    g.add(combo_row("Snap key", "Hold while dragging to choose a zone", s, "snap-modifier",
                    [("ctrl", "Ctrl"), ("alt", "Alt"), ("shift", "Shift"), ("super", "Super")]))
    page.add(g)

    g = Adw.PreferencesGroup(title="Spacing")
    g.add(spin_row("Gap between windows", "Pixels", s, "inner-gap", 0, 64))
    g.add(spin_row("Screen margin", "Pixels", s, "outer-gap", 0, 128))
    page.add(g)

    g = Adw.PreferencesGroup(title="Keyboard", description="Resize tiles by dragging a window edge; neighbours follow.")
    for keys, what in SHORTCUTS:
        row = Adw.ActionRow(title=what)
        row.add_suffix(Gtk.Label(label=keys, css_classes=["dim-label", "monospace"]))
        g.add(row)
    page.add(g)
    return page


# ---- Hardware & drivers ------------------------------------------------------------

def run_text(argv, timeout=60):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return (p.stdout + p.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return str(e)


def hardware_page(window):
    page = Adw.PreferencesPage(title="Hardware", icon_name="computer-symbolic")
    hw = hardware()
    g = Adw.PreferencesGroup(title="This computer", description="Detected at boot by iron-hwprofile")
    cpu = hw.get("cpu", {})

    def info(title, value):
        r = Adw.ActionRow(title=title, subtitle=str(value))
        r.set_subtitle_selectable(True)
        g.add(r)
    info("Processor", f"{cpu.get('model') or cpu.get('vendor', 'unknown')} — {cpu.get('threads', '?')} threads")
    info("Memory", f"{hw.get('memory', {}).get('total_mib', 0) / 1024:.1f} GiB")
    gpus = hw.get("gpus", [])
    info("Graphics", ", ".join(f"{x['vendor']} ({x['driver'] or 'no driver'})" for x in gpus) or "none detected")
    info("Architecture", hw.get("arch", os.uname().machine))
    info("Performance profile", {"low": "Light — animations and indexing reduced",
                                 "standard": "Standard", "high": "High"}.get(hw.get("tier"), "unknown"))
    info("Virtualization (KVM)", "available" if hw.get("kvm") else "not available")
    page.add(g)

    g2 = Adw.PreferencesGroup(title="Drivers",
                              description="Proprietary drivers (for example NVIDIA) come from Ubuntu's signed archive.")
    status = Adw.ActionRow(title="Recommended drivers", subtitle="Not checked yet")
    check = Gtk.Button(label="Check", valign=Gtk.Align.CENTER)
    status.add_suffix(check)
    g2.add(status)
    install = Adw.ButtonRow(title="Install recommended drivers")
    install.set_sensitive(False)
    g2.add(install)
    reset = Adw.ButtonRow(title="Reset graphics drivers (recovery)")
    reset.add_css_class("destructive-action")
    g2.add(reset)

    def do_check(_b):
        status.set_subtitle("Checking…")

        def work():
            out = run_text(["ubuntu-drivers", "list", "--recommended"])
            GLib.idle_add(done, out)

        def done(out):
            lines = [ln for ln in out.splitlines() if ln and "ERROR" not in ln]
            status.set_subtitle(", ".join(lines) if lines else "No additional drivers needed")
            install.set_sensitive(bool(lines))
        threading.Thread(target=work, daemon=True).start()
    check.connect("clicked", do_check)
    install.connect("activated", lambda *_: window.run_privileged(
        ["iron-drivers", "install"], "Installing drivers", "Restart to use the new drivers."))
    reset.connect("activated", lambda *_: window.run_privileged(
        ["iron-drivers", "reset-graphics"], "Resetting graphics drivers", "Restart to finish."))
    page.add(g2)
    return page


# ---- Updates -----------------------------------------------------------------------------

def updates_page(window):
    page = Adw.PreferencesPage(title="Updates", icon_name="software-update-available-symbolic")
    g = Adw.PreferencesGroup(title="Software updates",
                             description="Ingot uses Ubuntu's signed archives; security updates install automatically.")
    auto = Adw.ActionRow(title="Automatic security updates")
    enabled = "1" in run_text(["apt-config", "dump", "APT::Periodic::Unattended-Upgrade"])
    auto.set_subtitle("On" if enabled else "Off")
    g.add(auto)
    try:
        stamp = os.path.getmtime("/var/lib/apt/periodic/update-success-stamp")
        last = GLib.DateTime.new_from_unix_local(int(stamp)).format("%x %X")
    except OSError:
        last = "never"
    g.add(Adw.ActionRow(title="Last check", subtitle=last))
    if shutil.which("gnome-software"):
        sw = Adw.ButtonRow(title="Open Software updates")
        sw.connect("activated", lambda *_: spawn(["gnome-software", "--mode=updates"]))
        g.add(sw)
    now = Adw.ButtonRow(title="Update everything now")
    now.connect("activated", lambda *_: window.run_privileged(
        ["sh", "-c", "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -y full-upgrade"],
        "Updating Iron Linux", "Updates installed."))
    g.add(now)
    page.add(g)
    return page


# ---- About ---------------------------------------------------------------------------

def about_page():
    page = Adw.PreferencesPage(title="About", icon_name="help-about-symbolic")
    rel = os_release()
    g = Adw.PreferencesGroup()
    hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, halign=Gtk.Align.CENTER, margin_bottom=12)
    if os.path.exists("/usr/share/pixmaps/iron-ingot-wordmark.png"):
        pic = Gtk.Picture.new_for_filename("/usr/share/pixmaps/iron-ingot-wordmark.png")
        pic.set_size_request(360, 82)
        pic.set_content_fit(Gtk.ContentFit.CONTAIN)
        hero.append(pic)
    hero.append(Gtk.Label(label=rel.get("PRETTY_NAME", "Iron Linux"), css_classes=["title-2"]))
    g.add(hero)
    page.add(g)
    g = Adw.PreferencesGroup()
    for title, val in (("Edition", rel.get("VARIANT", "Ingot")), ("Version", rel.get("VERSION", "")),
                       ("Base", f"Ubuntu {rel.get('UBUNTU_CODENAME', '')}".strip()),
                       ("Kernel", os.uname().release), ("Desktop", "GNOME on Wayland")):
        g.add(Adw.ActionRow(title=title, subtitle=val))
    page.add(g)
    return page
