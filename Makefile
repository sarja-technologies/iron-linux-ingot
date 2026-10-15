# Iron Linux Ingot - component install targets (used by debian/rules) and checks.
#
#   make check                       run all offline checks (lint + unit tests)
#   make install-<pkg> DESTDIR=dir   install one binary package's files
#   make branding                    generate wallpapers/logos into build-area/branding

DESTDIR ?=
B := build-area/branding
WALLPAPER_SIZE ?= --width 3840 --height 2160
PY_SOURCES := system/bin/iron-hwprofile system/bin/iron-update tools/ingot-publish $(wildcard agent-desktops/iron_agents/*.py) \
	agent-desktops/bin/iron-agentd agent-desktops/bin/iron-agent \
	$(wildcard apps/iron-settings/iron_settings/*.py) apps/iron-settings/bin/iron-settings
SH_SOURCES := build/ingot-build build/lib/common.sh $(wildcard build/stages/*.sh) \
	system/bin/iron-drivers $(wildcard system/recovery/*) $(wildcard tests/vm/*.sh) \
	tests/shell/run-shell-tests.sh tests/shell/shell-test-inner.sh \
	agent-desktops/guest/iron-agent-session agent-desktops/guest/iron-agent-display-vm agent-desktops/guest/iron-agent-vm-setup \
	installer/scripts/postinstall installer/scripts/grub-defaults-fix

.PHONY: all check lint test branding clean $(addprefix install-,iron-base-files iron-archive-keyring iron-branding iron-shell iron-desktop-settings iron-settings iron-agent-desktops iron-installer-config)

all: branding

# ---- checks ---------------------------------------------------------------
check: lint test

lint:
	shellcheck -x $(SH_SOURCES)
	python3 -m py_compile $(PY_SOURCES)
	glib-compile-schemas --strict --dry-run desktop/shell/extensions/iron-tiling@ironlinux.org/schemas
	for f in desktop/shell/extensions/*/metadata.json; do python3 -m json.tool $$f >/dev/null || exit 1; done
	xmllint --noout agent-desktops/data/*.xml agent-desktops/data/*.policy agent-desktops/data/org.*.conf branding/src/*.xml

test:
	gjs -m tests/unit/test-tiling-layout.js
	python3 -m unittest discover -s tests/unit -p 'test_*.py' -v

# ---- branding (generated, not committed) -----------------------------------
branding: $(B)/.stamp

$(B)/.stamp: branding/tools/gen-wallpaper.py branding/src/*.svg
	mkdir -p $(B)
	python3 branding/tools/gen-wallpaper.py $(B) $(WALLPAPER_SIZE)
	cd branding/src && rsvg-convert -w 256 logo.svg -o ../../$(B)/iron-logo-256.png
	cd branding/src && rsvg-convert -h 96 wordmark.svg -o ../../$(B)/iron-ingot-gdm-logo.png
	cd branding/src && rsvg-convert -h 72 wordmark.svg -o ../../$(B)/watermark.png
	cd branding/src && rsvg-convert -h 128 wordmark.svg -o ../../$(B)/iron-ingot-wordmark.png
	python3 -c "from PIL import Image, ImageFilter, ImageEnhance; im=Image.open('$(B)/ingot-steel.jpg').convert('RGB').resize((1920,1080)); im=im.filter(ImageFilter.GaussianBlur(18)); ImageEnhance.Brightness(im).enhance(0.55).save('$(B)/iron-login.png', optimize=True)"
	touch $@

# ---- per-package installs ----------------------------------------------------
install-iron-base-files:
	# Shipped at the real paths; Ubuntu's copies are diverted in preinst.
	install -Dm644 system/identity/os-release $(DESTDIR)/usr/lib/os-release
	install -Dm644 system/identity/lsb-release $(DESTDIR)/etc/lsb-release
	install -Dm644 system/identity/issue $(DESTDIR)/etc/issue
	install -Dm644 system/identity/issue.net $(DESTDIR)/etc/issue.net
	install -Dm644 system/identity/legal $(DESTDIR)/etc/legal
	install -Dm755 system/identity/10-help-text $(DESTDIR)/etc/update-motd.d/10-help-text
	install -Dm644 system/apt/iron-no-snap.pref $(DESTDIR)/etc/apt/preferences.d/iron-no-snap.pref
	install -Dm644 system/apt/mozilla.pref $(DESTDIR)/etc/apt/preferences.d/mozilla.pref
	install -Dm644 system/apt/mozilla.sources $(DESTDIR)/etc/apt/sources.list.d/mozilla.sources
	install -Dm644 system/keyrings/packages.mozilla.org.gpg $(DESTDIR)/usr/share/keyrings/packages.mozilla.org.gpg
	install -Dm644 system/apt/50iron-unattended-upgrades $(DESTDIR)/etc/apt/apt.conf.d/52iron-unattended-upgrades
	install -Dm644 system/sysctl/90-iron.conf $(DESTDIR)/usr/lib/sysctl.d/90-iron.conf
	install -Dm644 system/zram/zram-generator.conf $(DESTDIR)/usr/lib/systemd/zram-generator.conf.d/90-iron.conf
	install -Dm644 system/grub/iron.cfg $(DESTDIR)/etc/default/grub.d/90-iron.cfg
	install -Dm755 system/bin/iron-hwprofile $(DESTDIR)/usr/libexec/iron/iron-hwprofile
	install -Dm755 system/bin/iron-drivers $(DESTDIR)/usr/libexec/iron/iron-drivers
	install -d $(DESTDIR)/usr/bin
	ln -sf ../libexec/iron/iron-drivers $(DESTDIR)/usr/bin/iron-drivers
	ln -sf ../libexec/iron/iron-hwprofile $(DESTDIR)/usr/bin/iron-hwprofile
	install -Dm755 system/bin/iron-update $(DESTDIR)/usr/bin/iron-update
	install -Dm644 system/systemd/iron-hwprofile.service $(DESTDIR)/usr/lib/systemd/system/iron-hwprofile.service
	install -Dm755 system/recovery/iron-reset-graphics $(DESTDIR)/usr/lib/recovery-mode/options/iron-reset-graphics
	install -Dm755 system/recovery/iron-disable-agents $(DESTDIR)/usr/lib/recovery-mode/options/iron-disable-agents
	install -Dm644 desktop/defaults/dconf-profile-user $(DESTDIR)/etc/dconf/profile/user
	install -d $(DESTDIR)/etc/dconf/db/iron-hw.d

# Public archive keys trusted for the Iron package source: every *.gpg (binary
# OpenPGP export) in packaging/archive-keys/. Image builds add their local
# development key there in the builder copy only (never committed).
install-iron-archive-keyring:
	@ls packaging/archive-keys/*.gpg >/dev/null 2>&1 || { echo "no archive keys in packaging/archive-keys/" >&2; exit 1; }
	install -d $(DESTDIR)/usr/share/keyrings
	cat packaging/archive-keys/*.gpg > $(DESTDIR)/usr/share/keyrings/iron-archive-keyring.gpg
	chmod 644 $(DESTDIR)/usr/share/keyrings/iron-archive-keyring.gpg

install-iron-branding: branding
	install -d $(DESTDIR)/usr/share/backgrounds/iron
	install -m644 $(B)/ingot-*.jpg $(DESTDIR)/usr/share/backgrounds/iron/
	install -Dm644 branding/src/iron-backgrounds.xml $(DESTDIR)/usr/share/gnome-background-properties/iron-backgrounds.xml
	install -Dm644 branding/src/logo.svg $(DESTDIR)/usr/share/icons/hicolor/scalable/apps/iron-logo.svg
	install -Dm644 $(B)/iron-logo-256.png $(DESTDIR)/usr/share/icons/hicolor/256x256/apps/iron-logo.png
	install -Dm644 branding/src/logo.svg $(DESTDIR)/usr/share/pixmaps/iron-logo.svg
	install -Dm644 $(B)/iron-ingot-gdm-logo.png $(DESTDIR)/usr/share/pixmaps/iron-ingot-gdm-logo.png
	install -Dm644 $(B)/iron-ingot-wordmark.png $(DESTDIR)/usr/share/pixmaps/iron-ingot-wordmark.png
	install -Dm644 branding/src/iron-ingot.plymouth.in $(DESTDIR)/usr/share/plymouth/themes/iron-ingot/iron-ingot.plymouth
	install -Dm644 $(B)/watermark.png $(DESTDIR)/usr/share/plymouth/themes/iron-ingot/watermark.png
	# Reuse Ubuntu's maintained spinner frames and prompt assets.
	cd /usr/share/plymouth/themes/spinner && for f in *.png; do \
		[ "$$f" = watermark.png ] && continue; \
		ln -sf ../spinner/$$f $(abspath $(DESTDIR))/usr/share/plymouth/themes/iron-ingot/$$f; done

install-iron-shell:
	install -d $(DESTDIR)/usr/share/gnome-shell/extensions
	cp -r desktop/shell/extensions/iron-shell@ironlinux.org desktop/shell/extensions/iron-tiling@ironlinux.org \
		$(DESTDIR)/usr/share/gnome-shell/extensions/
	install -m644 agent-desktops/data/org.ironlinux.AgentDesktops1.xml \
		$(DESTDIR)/usr/share/gnome-shell/extensions/iron-shell@ironlinux.org/
	install -Dm644 desktop/shell/extensions/iron-tiling@ironlinux.org/schemas/org.ironlinux.tiling.gschema.xml \
		$(DESTDIR)/usr/share/glib-2.0/schemas/org.ironlinux.tiling.gschema.xml
	rm -rf $(DESTDIR)/usr/share/gnome-shell/extensions/iron-tiling@ironlinux.org/schemas
	desktop/shell/gdm/build-gdm-theme.sh /usr/share/gnome-shell/theme/Yaru/gnome-shell-theme.gresource \
		desktop/shell/gdm/iron-gdm.css $(B)/iron-login.png \
		$(DESTDIR)/usr/share/gnome-shell/theme/Iron/gnome-shell-theme.gresource

install-iron-desktop-settings:
	install -Dm644 desktop/defaults/90_iron-ingot.gschema.override $(DESTDIR)/usr/share/glib-2.0/schemas/90_iron-ingot.gschema.override
	install -Dm644 desktop/defaults/gdm-95-iron-settings $(DESTDIR)/usr/share/gdm/dconf/95-iron-settings

install-iron-settings:
	$(MAKE) -C apps/iron-settings install DESTDIR=$(abspath $(DESTDIR))

install-iron-agent-desktops:
	$(MAKE) -C agent-desktops install DESTDIR=$(abspath $(DESTDIR))

install-iron-installer-config:
	$(MAKE) -C installer install DESTDIR=$(abspath $(DESTDIR))

clean:
	rm -rf build-area
	find . -name __pycache__ -prune -exec rm -rf {} +
