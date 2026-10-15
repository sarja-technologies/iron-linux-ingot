#!/usr/bin/env python3
"""Open a plain resizable GTK4 window titled by argv[1] (headless shell tests)."""
import sys
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

app = Gtk.Application(application_id=None)

def activate(a):
    w = Gtk.ApplicationWindow(application=a, title=sys.argv[1])
    w.set_default_size(500, 400)
    w.set_child(Gtk.Label(label=sys.argv[1]))
    w.present()

app.connect("activate", activate)
app.run([])
