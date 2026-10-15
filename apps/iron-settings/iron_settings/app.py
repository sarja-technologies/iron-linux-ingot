"""Iron Settings application window."""
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import pages  # noqa: E402
from .agents import AgentsPage  # noqa: E402

APP_ID = "org.ironlinux.Settings"
CSS = b"""
.iron-sidebar row { border-radius: 10px; margin: 2px 6px; }
.iron-wallpaper picture { border-radius: 10px; }
"""


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Iron Settings", default_width=1060, default_height=760)
        self.toasts = Adw.ToastOverlay()
        self.pages = {}
        split = Adw.NavigationSplitView(sidebar_width_fraction=0.26)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)

        self.content_page = Adw.NavigationPage(title="Appearance")
        tv = Adw.ToolbarView()
        tv.add_top_bar(Adw.HeaderBar())
        tv.set_content(self.stack)
        self.content_page.set_child(tv)

        sidebar = Gtk.ListBox(css_classes=["navigation-sidebar", "iron-sidebar"])
        entries = [
            ("appearance", "Appearance", "preferences-desktop-appearance-symbolic", lambda: pages.appearance_page()),
            ("tiling", "Tiling", "view-grid-symbolic", lambda: pages.tiling_page()),
            ("agents", "Agent Desktops", "computer-symbolic", lambda: AgentsPage(self)),
            ("hardware", "Hardware & Drivers", "applications-engineering-symbolic", lambda: pages.hardware_page(self)),
            ("updates", "Updates", "software-update-available-symbolic", lambda: pages.updates_page(self)),
            ("about", "About", "help-about-symbolic", lambda: pages.about_page()),
        ]
        self._factories = {k: (title, f) for k, title, _i, f in entries}
        self._keys = []
        for key, title, icon, _f in entries:
            box = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=6)
            box.append(Gtk.Image(icon_name=icon))
            box.append(Gtk.Label(label=title, xalign=0))
            sidebar.append(box)
            self._keys.append(key)
        sidebar.connect("row-activated", lambda _l, row: self.show_page(self._keys[row.get_index()]))
        self.sidebar = sidebar

        stv = Adw.ToolbarView()
        stv.add_top_bar(Adw.HeaderBar(title_widget=Adw.WindowTitle(title="Iron Settings")))
        stv.set_content(Gtk.ScrolledWindow(child=sidebar))
        split.set_sidebar(Adw.NavigationPage(child=stv, title="Iron Settings"))
        split.set_content(self.content_page)
        self.split = split
        self.toasts.set_child(split)
        self.set_content(self.toasts)

        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 640sp"))
        bp.add_setter(split, "collapsed", True)
        self.add_breakpoint(bp)

    def show_page(self, key):
        if key not in self.pages:
            title, factory = self._factories[key]
            self.pages[key] = factory()
            self.stack.add_named(self.pages[key], key)
        self.stack.set_visible_child_name(key)
        self.content_page.set_title(self._factories[key][0])
        self.sidebar.select_row(self.sidebar.get_row_at_index(self._keys.index(key)))
        self.split.set_show_content(True)
        return self.pages[key]

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(str(text))[:300], timeout=5))

    def run_privileged(self, argv, title, done_msg, on_finish=None):
        """Run a command through pkexec, streaming output into a dialog."""
        dlg = Adw.Dialog(title=title, content_width=640, content_height=420)
        tv = Adw.ToolbarView()
        tv.add_top_bar(Adw.HeaderBar())
        buf = Gtk.TextBuffer()
        view = Gtk.TextView(buffer=buf, editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                            top_margin=8, left_margin=8, right_margin=8)
        tv.set_content(Gtk.ScrolledWindow(child=view, vexpand=True))
        dlg.set_child(tv)
        dlg.present(self)
        try:
            proc = Gio.Subprocess.new(["pkexec", *argv],
                                      Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)
        except GLib.Error as e:
            buf.set_text(e.message)
            return
        stream = Gio.DataInputStream.new(proc.get_stdout_pipe())

        def read_line(s, res):
            line, _len = s.read_line_finish_utf8(res)
            if line is None:
                return
            buf.insert(buf.get_end_iter(), line + "\n")
            view.scroll_to_iter(buf.get_end_iter(), 0, False, 0, 0)
            s.read_line_async(GLib.PRIORITY_DEFAULT, None, read_line)
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, read_line)

        def finished(p, res):
            p.wait_finish(res)
            ok = p.get_successful()
            buf.insert(buf.get_end_iter(), ("\n✔ " + done_msg) if ok else "\n✖ Failed (see output above)")
            self.toast(done_msg if ok else f"{title}: failed")
            if on_finish:
                on_finish()
        proc.wait_async(None, finished)


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.add_main_option("page", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING, "Open a page", "PAGE")
        self.add_main_option("agent", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING, "Show an agent", "ID")
        self.add_main_option("tab", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING, "Agent tab", "TAB")
        self.add_main_option("open", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING, "Open an agent desktop", "ID")
        self.win = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        css = Gtk.CssProvider()
        css.load_from_data(CSS, -1)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_command_line(self, cmd):
        opts = cmd.get_options_dict().end().unpack()
        if not self.win:
            self.win = Window(self)
        page = opts.get("page", "appearance")
        if opts.get("agent") or opts.get("open"):
            page = "agents"
        p = self.win.show_page(page if page in self.win._keys else "appearance")
        if opts.get("agent"):
            p.show_agent(opts["agent"], opts.get("tab"))
        if opts.get("open"):
            p.open_desktop(opts["open"])
        self.win.present()
        return 0


def main():
    return App().run(sys.argv)
