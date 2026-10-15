# Iron Agent Desktops

Isolated desktops where AI agents work with a bounded share of the computer,
while you keep using your own desktop. Each agent is a separate execution
environment — not a GNOME workspace — that you can watch, instruct, pause,
snapshot, and stop.

```
Main desktop (you)              Agent Desktop 1 (container)      Agent Desktop 2 (VM)
GNOME / Wayland                 systemd-nspawn + user namespace  QEMU/KVM, own kernel
your files, your apps           own ext4 disk, cgroup limits     qcow2 overlay, cgroup limits
        │                       Xvnc + Openbox (unix socket)     QEMU VNC (unix socket)
        └── Iron Settings / iron-agent / panel indicator ── D-Bus ── iron-agentd (root, on demand)
```

## Using it

1. **Iron Settings → Agent Desktops → turn on** (administrator approval).
2. **Prepare** the agent image (downloads a minimal Ubuntu with a light desktop;
   optional Claude Code, Codex CLI, Firefox, VM support).
3. **+** to create an agent: name, agent tool, isolation (container or VM) and a
   preset — **Light / Balanced / Heavy / Custom**.
4. **Start**, then **Open desktop** to watch it, type instructions, answer
   approval requests, review **Results** and **Export** what you want to keep.

The same is available from the terminal:

```sh
iron-agent enable
sudo iron-agent image build --runtime claude-code --browser   # add --vm for VM agents
iron-agent create "Claude coding" --preset balanced --runtime claude-code
iron-agent start a1b2c3d4e5
iron-agent share a1b2c3d4e5 ~/Projects/site --writable        # applies at next start
iron-agent send a1b2c3d4e5 "run the test suite and fix failures"
iron-agent approvals ; iron-agent approve <request-id>
iron-agent outputs a1b2c3d4e5 ; iron-agent export a1b2c3d4e5 logs/task-001.log ~/Downloads
iron-agent open a1b2c3d4e5                                    # TigerVNC viewer
```

## What is enforced, and by what

| Control | Container agents | VM agents |
|---|---|---|
| Identity | private user namespace: agent root = unprivileged host UID range (per agent, fixed) | separate kernel; QEMU runs as unprivileged `iron-agent-vm` |
| CPU threads | cgroup cpuset (`AllowedCPUs`, highest CPUs first, CPU 0 left to the desktop) | vCPUs + cgroup cpuset |
| CPU time | cgroup `CPUQuota` | cgroup `CPUQuota` on QEMU |
| Memory | cgroup `MemoryMax` + `MemorySwapMax=0` (no swap escape) | guest RAM + cgroup cap (RAM + 384 MiB) |
| Storage | size of the agent's ext4 image (hard limit) | qcow2 virtual size |
| Processes | `TasksMax` | `TasksMax` |
| Time limit | `RuntimeMaxSec` | `RuntimeMaxSec` |
| Network | none by default (private netns); "internet" = user-mode `pasta`, no route to host services | none by default (`restrict=on`); "internet" = user-mode NAT |
| Host files | none, except folders you share (idmapped bind mounts, read-only by default; revoke is immediate) | none (exchange files through the outbox) |
| Devices | `DevicePolicy=closed`; GPU render node only if granted | `DevicePolicy=closed` + `/dev/kvm` |
| Root inside | `iron-elevate CMD` runs only after you approve that exact command | same |
| All agents together | `iron-agents.slice`: `MemoryMax=85%`, lower CPU/IO weight than the desktop | same |

Limits above half of the computer (CPU or memory) need administrator
authentication (`org.ironlinux.agentdesktops.allocate-beyond-limits`). The
service always keeps `host_reserved_memory_mib` (default 2 GiB) for you.

### GPU — honest limits

* **Container agents** can be granted *shared* access to the GPU render node
  (`/dev/dri/renderD*`) for Mesa/Vulkan/OpenCL compute. **GPU time and GPU
  memory are not partitioned or reserved**; the desktop and agents compete.
* **NVIDIA proprietary** stacks inside agents are not set up automatically.
* **VM agents** have no GPU passthrough in this release.
* Hardware partitioning (SR-IOV) is only *reported* when the hardware exposes
  it; Iron does not configure it yet.

## Approvals

Agents ask before sensitive actions with `iron-approve` (any process) or
`iron-elevate` (root command inside the agent). Claude Code inside agents is
configured with a **managed** `PreToolUse` hook (`/etc/claude-code/managed-settings.json`,
not writable by the agent) so Bash, file writes and web fetches wait for you.
Requests are untrusted input: size-limited, shown as data, and for root
commands the text you see is derived from the actual argv; each approval is
bound to the SHA-256 of the request it answers and can be used once.

## Costs: containers vs virtual machines

| | Container | VM |
|---|---|---|
| Idle memory overhead | ~60–120 MiB (systemd + Xvnc + Openbox) | guest kernel + userspace, ~250–400 MiB, plus QEMU |
| Start time | seconds | 10–40 s (KVM); minutes without KVM |
| Isolation boundary | Linux kernel namespaces + cgroups (shared kernel) | hardware virtualization (separate kernel) |
| Disk per agent | full copy of the base image (~1–2 GiB) | qcow2 overlay (only changes) |
| Host folders | yes (idmapped) | not yet |
| GPU | shared render node | none |
| ARM64 | yes | yes with KVM on ARM64 hardware; TCG emulation otherwise (slow) |

When the feature is off — or on with no agent running — nothing is reserved:
`iron-agentd` is D-Bus activated and exits after `idle_exit_seconds`.

## Integrations

* **Claude Code** (`claude-code` runtime): installed into the image with npm;
  sign in inside the agent desktop. Tool use is gated by the managed hook.
* **OpenAI Codex CLI** (`codex` runtime): `codex exec --sandbox workspace-write`.
* **AgentDock / AgentDock Pro** (`agentdock` runtime): run the AgentDock
  AppImage you provide via a shared folder inside the agent desktop; everything
  it spawns stays inside the isolation boundary.
* Local first: no remote orchestration service is involved.

## Status

See `docs/STATUS.md` in the repository for what has been validated end-to-end.
