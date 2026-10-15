# Iron Linux installer configuration (Calamares) - install layout.
DESTDIR ?=
BRANDING_BUILD ?= ../build-area/branding

install:
	install -Dm644 settings.conf $(DESTDIR)/etc/calamares/settings.conf
	install -d $(DESTDIR)/etc/calamares/modules $(DESTDIR)/etc/calamares/branding/iron
	install -m644 modules/*.conf $(DESTDIR)/etc/calamares/modules/
	install -m644 branding/iron/branding.desc branding/iron/show.qml $(DESTDIR)/etc/calamares/branding/iron/
	python3 tools/gen-images.py $(BRANDING_BUILD) $(DESTDIR)/etc/calamares/branding/iron $(DESTDIR)/usr/share/iron-installer
	install -Dm755 scripts/postinstall $(DESTDIR)/usr/libexec/iron-installer/postinstall
	install -Dm755 scripts/install-iron-linux $(DESTDIR)/usr/bin/install-iron-linux
	install -Dm644 data/install-iron-linux.desktop $(DESTDIR)/usr/share/applications/install-iron-linux.desktop
	install -Dm644 data/95_iron-live.gschema.override $(DESTDIR)/usr/share/glib-2.0/schemas/95_iron-live.gschema.override
