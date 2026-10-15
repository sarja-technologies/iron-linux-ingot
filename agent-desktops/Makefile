# Iron Agent Desktops - install layout (driven by the top-level Makefile).
DESTDIR ?=
LIB := $(DESTDIR)/usr/lib/iron-agents

install:
	install -d $(LIB)/iron_agents
	install -m644 iron_agents/*.py $(LIB)/iron_agents/
	install -Dm755 bin/iron-agentd $(DESTDIR)/usr/libexec/iron/iron-agentd
	install -Dm755 bin/iron-agent $(DESTDIR)/usr/bin/iron-agent
	install -Dm644 data/org.ironlinux.AgentDesktops1.xml $(DESTDIR)/usr/share/dbus-1/interfaces/org.ironlinux.AgentDesktops1.xml
	install -Dm644 data/org.ironlinux.AgentDesktops1.conf $(DESTDIR)/usr/share/dbus-1/system.d/org.ironlinux.AgentDesktops1.conf
	install -Dm644 data/org.ironlinux.AgentDesktops1.service $(DESTDIR)/usr/share/dbus-1/system-services/org.ironlinux.AgentDesktops1.service
	install -Dm644 data/org.ironlinux.agentdesktops.policy $(DESTDIR)/usr/share/polkit-1/actions/org.ironlinux.agentdesktops.policy
	install -Dm644 data/iron-agentd.service $(DESTDIR)/usr/lib/systemd/system/iron-agentd.service
	install -Dm644 data/iron.slice $(DESTDIR)/usr/lib/systemd/system/iron.slice
	install -Dm644 data/iron-agents.slice $(DESTDIR)/usr/lib/systemd/system/iron-agents.slice
	install -Dm644 data/agent-desktops.conf $(DESTDIR)/etc/iron/agent-desktops.conf
	install -d $(DESTDIR)/usr/share/iron-agents/runtimes $(DESTDIR)/usr/share/iron-agents/guest/units
	install -m644 runtimes/*.json $(DESTDIR)/usr/share/iron-agents/runtimes/
	install -m755 guest/iron-agent-runner guest/iron-agent-session guest/iron-agent-vm-setup guest/iron-approve guest/iron-elevate \
		$(DESTDIR)/usr/share/iron-agents/guest/
	install -m644 guest/claude-managed-settings.json $(DESTDIR)/usr/share/iron-agents/guest/
	install -m644 guest/units/*.service $(DESTDIR)/usr/share/iron-agents/guest/units/
	install -Dm644 README.md $(DESTDIR)/usr/share/doc/iron-agent-desktops/README.md
