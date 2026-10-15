"""Async client for the org.ironlinux.AgentDesktops1 system service."""
import json

from gi.repository import Gio, GLib

BUS, PATH, IFACE = "org.ironlinux.AgentDesktops1", "/org/ironlinux/AgentDesktops1", "org.ironlinux.AgentDesktops1"


def _err_text(e):
    msg = e.message
    if Gio.DBusError.is_remote_error(e):
        msg = msg.split(": ", 1)[-1] if ": " in msg else msg
    if "ServiceUnknown" in e.message or "not provided by any .service" in e.message:
        return "The Agent Desktops service is not installed."
    return msg


class AgentBus:
    """Every call is asynchronous so polkit prompts never freeze the window."""

    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        self._subs = []

    def call(self, method, sig="", args=(), on_done=None, on_error=None, parse=True):
        params = GLib.Variant(f"({sig})", tuple(args)) if sig else None

        def done(bus, res):
            try:
                v = bus.call_finish(res).unpack()
                val = v[0] if v else None
                if parse and isinstance(val, str) and val[:1] in "[{":
                    val = json.loads(val)
                if on_done:
                    on_done(val)
            except GLib.Error as e:
                if on_error:
                    on_error(_err_text(e))

        self.bus.call(BUS, PATH, IFACE, method, params, None,
                      Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION, 180000, None, done)

    def subscribe(self, signal, callback):
        sid = self.bus.signal_subscribe(BUS, IFACE, signal, PATH, None, Gio.DBusSignalFlags.NONE,
                                        lambda *a: callback(*a[5].unpack()))
        self._subs.append(sid)
        return sid

    def close(self):
        for s in self._subs:
            self.bus.signal_unsubscribe(s)
        self._subs = []
