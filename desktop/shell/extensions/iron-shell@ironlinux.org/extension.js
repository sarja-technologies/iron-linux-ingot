// Iron Shell - Ingot panel identity and Agent Desktops indicator.
//
// Kept intentionally small: styling lives in stylesheet.css, and the only
// runtime work is a D-Bus proxy that exists while the Agent Desktops service
// is present on the system bus (no polling).

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GObject from 'gi://GObject';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as MessageTray from 'resource:///org/gnome/shell/ui/messageTray.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const BUS_NAME = 'org.ironlinux.AgentDesktops1';
const OBJ_PATH = '/org/ironlinux/AgentDesktops1';
const CONF_PATH = '/etc/iron/agent-desktops.conf';

function loadInterface(dir) {
    const file = dir.get_child('org.ironlinux.AgentDesktops1.xml');
    const [, bytes] = file.load_contents(null);
    return new TextDecoder().decode(bytes);
}

const STATE_LABEL = {
    running: 'Running', paused: 'Paused', stopped: 'Stopped', starting: 'Starting',
    waiting: 'Needs approval', failed: 'Failed', finished: 'Finished',
};
const LIVE_STATES = ['running', 'starting', 'waiting', 'paused'];
const DONE_STATES = ['stopped', 'finished', 'failed'];

const AgentIndicator = GObject.registerClass(
class AgentIndicator extends PanelMenu.Button {
    _init(ext) {
        super._init(0.5, 'Agent Desktops');
        this._ext = ext;
        this._agents = [];
        this.add_style_class_name('iron-agent-indicator');
        const box = new St.BoxLayout({style_class: 'panel-status-menu-box'});
        this._icon = new St.Icon({
            gicon: Gio.icon_new_for_string(ext.dir.get_child('icons/iron-agent-symbolic.svg').get_path()),
            style_class: 'system-status-icon',
        });
        this._count = new St.Label({text: '', y_align: Clutter.ActorAlign.CENTER, style_class: 'iron-agent-count'});
        box.add_child(this._icon);
        box.add_child(this._count);
        this.add_child(box);
        this.menu.connect('open-state-changed', (_m, open) => {
            if (open)
                this._rebuildMenu();
        });
        this._rebuildMenu();
    }

    update(agents) {
        this._agents = agents;
        const active = agents.filter(a => LIVE_STATES.includes(a.state));
        this._count.text = active.length ? String(active.length) : '';
        this.visible = this._ext.enabled;
        if (agents.some(a => a.state === 'waiting'))
            this.add_style_class_name('iron-agent-attention');
        else
            this.remove_style_class_name('iron-agent-attention');
    }

    _rebuildMenu() {
        this.menu.removeAll();
        if (!this._agents.length)
            this.menu.addMenuItem(new PopupMenu.PopupMenuItem('No agent desktops yet', {reactive: false}));
        for (const a of this._agents) {
            const sub = new PopupMenu.PopupSubMenuMenuItem(`${a.name} — ${STATE_LABEL[a.state] ?? a.state}`);
            const add = (label, fn) => sub.menu.addAction(label, fn);
            if (['running', 'paused', 'waiting'].includes(a.state))
                add('Open desktop', () => this._ext.launchSettings(['--open', a.id]));
            if (a.state === 'running')
                add('Pause', () => this._ext.call('Pause', a.id));
            if (a.state === 'paused')
                add('Resume', () => this._ext.call('Resume', a.id));
            if (DONE_STATES.includes(a.state))
                add('Start', () => this._ext.call('Start', a.id));
            else
                add('Stop', () => this._ext.call('Stop', a.id));
            add('Details…', () => this._ext.launchSettings(['--agent', a.id]));
            this.menu.addMenuItem(sub);
        }
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this.menu.addAction('Agent Desktops Settings', () => this._ext.launchSettings(['--page', 'agents']));
    }
});

export default class IronShellExtension extends Extension {
    enable() {
        this.enabled = false;
        Main.panel.add_style_class_name('iron-panel');
        this._addLogo();

        this._indicator = new AgentIndicator(this);
        this._indicator.visible = false;
        Main.panel.addToStatusArea('iron-agents', this._indicator, 0, 'right');

        const ProxyClass = Gio.DBusProxy.makeProxyWrapper(loadInterface(this.dir));
        this._watch = Gio.bus_watch_name(Gio.BusType.SYSTEM, BUS_NAME,
            Gio.BusNameWatcherFlags.NONE,
            () => this._connectProxy(ProxyClass),
            () => this._dropProxy());

        // The service is D-Bus activated and exits when idle, so the "feature
        // enabled" flag is read from its config file and watched for changes.
        this._conf = Gio.File.new_for_path(CONF_PATH);
        this._confMonitor = this._conf.monitor_file(Gio.FileMonitorFlags.NONE, null);
        this._confMonitor.connect('changed', () => this._readEnabledFlag());
        this._readEnabledFlag();
    }

    disable() {
        if (this._watch)
            Gio.bus_unwatch_name(this._watch);
        this._watch = 0;
        this._confMonitor?.cancel();
        this._confMonitor = null;
        this._dropProxy();
        this._indicator?.destroy();
        this._indicator = null;
        this._logo?.destroy();
        this._logo = null;
        Main.panel.remove_style_class_name('iron-panel');
        this._approvalNotes = null;
        this._source?.destroy();
        this._source = null;
    }

    _addLogo() {
        const activities = Main.panel.statusArea.activities;
        if (!activities)
            return;
        this._logo = new St.Icon({
            gicon: Gio.icon_new_for_string(this.dir.get_child('icons/iron-logo-symbolic.svg').get_path()),
            style_class: 'iron-panel-logo',
        });
        const child = activities.get_first_child();
        if (child instanceof St.BoxLayout)
            child.insert_child_at_index(this._logo, 0);
        else
            activities.add_child(this._logo);
    }

    _readEnabledFlag() {
        this._conf.load_contents_async(null, (file, res) => {
            let enabled = false;
            try {
                const [, bytes] = file.load_contents_finish(res);
                enabled = /^\s*enabled\s*=\s*true\s*$/m.test(new TextDecoder().decode(bytes));
            } catch (_e) {
                // Package not installed or feature never configured.
            }
            this.enabled = enabled;
            this._indicator?.update(this._indicator._agents);
        });
    }

    _connectProxy(ProxyClass) {
        new ProxyClass(Gio.DBus.system, BUS_NAME, OBJ_PATH, (proxy, error) => {
            if (error) {
                console.warn(`iron-shell: agent proxy: ${error.message}`);
                return;
            }
            if (!this._indicator)
                return;
            this._proxy = proxy;
            this._sigs = [
                proxy.connectSignal('AgentChanged', () => this._refresh()),
                proxy.connectSignal('ApprovalRequested', (_p, _s, [json]) => this._onApproval(json)),
                proxy.connectSignal('AgentFinished', (_p, _s, [id, summary]) => this._onFinished(id, summary)),
            ];
            this._refresh();
        });
    }

    _dropProxy() {
        if (this._proxy && this._sigs)
            this._sigs.forEach(id => this._proxy.disconnectSignal(id));
        this._proxy = null;
        this._sigs = null;
    }

    _refresh() {
        this._proxy?.ListAgentsRemote((r, e) => {
            if (!e && this._indicator)
                this._indicator.update(JSON.parse(r[0]));
        });
        // Approval banners are critical (they stay up): withdraw the ones decided
        // elsewhere (CLI, Iron Settings) or whose agent was stopped or deleted.
        if (this._approvalNotes?.size) {
            this._proxy?.ListApprovalsRemote((r, e) => {
                if (e || !this._approvalNotes)
                    return;
                const pending = new Set(JSON.parse(r[0]).map(req => req.id));
                for (const [id, n] of this._approvalNotes) {
                    if (!pending.has(id))
                        n.destroy();
                }
            });
        }
    }

    call(method, ...args) {
        this._proxy?.[`${method}Remote`](...args, (_r, err) => {
            if (err)
                this._notify('Agent Desktops', err.message);
        });
    }

    launchSettings(args) {
        try {
            Gio.Subprocess.new(['iron-settings', ...args], Gio.SubprocessFlags.NONE);
        } catch (e) {
            this._notify('Agent Desktops', `Could not open Iron Settings: ${e.message}`);
        }
    }

    _notify(title, body, urgent = false) {
        if (!this._source) {
            this._source = new MessageTray.Source({
                title: 'Agent Desktops',
                iconName: 'computer-symbolic',
            });
            this._source.connect('destroy', () => (this._source = null));
            Main.messageTray.add(this._source);
        }
        const n = new MessageTray.Notification({source: this._source, title, body});
        if (urgent)
            n.urgency = MessageTray.Urgency.CRITICAL;
        this._source.addNotification(n);
        return n;
    }

    _onApproval(json) {
        let req;
        try {
            req = JSON.parse(json);
        } catch (_e) {
            return;
        }
        const n = this._notify(`${req.agent_name ?? 'Agent'} needs approval`, req.summary ?? '', true);
        n.addAction('Allow', () => this.call('Decide', req.id, true));
        n.addAction('Deny', () => this.call('Decide', req.id, false));
        this._approvalNotes ??= new Map();
        this._approvalNotes.set(req.id, n);
        n.connect('destroy', () => this._approvalNotes?.delete(req.id));
        this._refresh();
    }

    _onFinished(id, summary) {
        const n = this._notify('Agent finished', summary || id);
        n.addAction('Review results', () => this.launchSettings(['--agent', id, '--tab', 'outputs']));
        this._refresh();
    }
}
