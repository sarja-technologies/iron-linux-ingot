"""polkit authorisation for D-Bus callers."""
from gi.repository import Gio, GLib

USE = "org.ironlinux.agentdesktops.use"
CONFIGURE = "org.ironlinux.agentdesktops.configure"
ALLOCATE_HIGH = "org.ironlinux.agentdesktops.allocate-beyond-limits"
MANAGE_ALL = "org.ironlinux.agentdesktops.manage-all"


class NotAuthorized(Exception):
    pass


def caller_uid(bus, sender):
    r = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                      "GetConnectionUnixUser", GLib.Variant("(s)", (sender,)),
                      GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, 5000, None)
    return r.unpack()[0]


def check(bus, sender, action, interactive=True):
    subject = ("system-bus-name", {"name": GLib.Variant("s", sender)})
    flags = 1 if interactive else 0  # AllowUserInteraction
    try:
        r = bus.call_sync("org.freedesktop.PolicyKit1", "/org/freedesktop/PolicyKit1/Authority",
                          "org.freedesktop.PolicyKit1.Authority", "CheckAuthorization",
                          GLib.Variant("((sa{sv})sa{ss}us)", (subject, action, {}, flags, "")),
                          GLib.VariantType("((bba{ss}))"), Gio.DBusCallFlags.NONE, 120000, None)
    except GLib.Error as e:
        raise NotAuthorized(f"authorization check failed: {e.message}") from e
    authorized = r.unpack()[0][0]
    if not authorized:
        raise NotAuthorized(f"not authorized ({action})")
    return True


def is_authorized(bus, sender, action):
    try:
        return check(bus, sender, action, interactive=False)
    except NotAuthorized:
        return False
