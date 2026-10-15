DESTDIR ?=
install:
	install -d $(DESTDIR)/usr/lib/iron-settings/iron_settings
	install -m644 iron_settings/*.py $(DESTDIR)/usr/lib/iron-settings/iron_settings/
	install -Dm755 bin/iron-settings $(DESTDIR)/usr/bin/iron-settings
	install -Dm644 data/org.ironlinux.Settings.desktop $(DESTDIR)/usr/share/applications/org.ironlinux.Settings.desktop
