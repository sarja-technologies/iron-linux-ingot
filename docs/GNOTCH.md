# Gnotch integration path

[Gnotch](https://github.com/crossainthero-lab/Gnotch) is an independent project:
an expandable notch for the GNOME top bar with an out-of-process addon
platform (Voice Notes with local speech-to-text, Agent Workspace that runs
Claude Code / Codex on approved tasks). Ingot packages it; it does not fork it.

## What Ingot does today (implemented)

* `packaging/gnotch/build-gnotch-deb.sh SRC OUT` builds a `gnotch` `.deb` from
  the **exact committed tree** of a Gnotch checkout (`git archive`), refusing
  any commit other than `packaging/gnotch/PINNED_COMMIT` (currently
  `ff7e1b2b`, Gnotch 0.1.0).
* System layout uses paths Gnotch already supports: extension in
  `/usr/share/gnome-shell/extensions/gnotch@gnotch.dev`, service and SDK in
  `/usr/share/gnotch`, official addons in `/usr/share/gnotch/addons`, session
  D-Bus activation for `org.gnotch.Service1`, `/usr/bin/gnotch-ctl`.
* `INGOT_GNOTCH_SRC=/path/to/checkout build/ingot-build ...` adds the package
  to the image. Any failure only prints a warning: **Gnotch never blocks the
  core OS build, boot, desktop or installer.**
* Installed but **not enabled**. Iron Settings → Appearance shows a *Gnotch*
  switch only when the package is present (adds/removes
  `gnotch@gnotch.dev` in `org.gnome.shell enabled-extensions`).
* Gnotch's addons stay disabled until the user enables them in Gnotch's own
  addon manager, with the permissions Gnotch displays.

## Compatibility rule

The `gnotch` package depends on `gnome-shell (>= 50), (<< 51)`, matching
Gnotch's `metadata.json`. When Ingot moves to a new GNOME major, the pin moves
to a Gnotch commit that declares that version, or the package is dropped from
the image for that release.

## Agent-connected workspace (planned, not implemented)

Gnotch's Agent Workspace runs agents as the user, unsandboxed (Gnotch's own
docs say so). The intended Ingot connection is a new Agent Workspace
connector that targets an **Iron Agent Desktop** instead of a local process:

| Gnotch action | Iron Agent Desktops call (system bus) |
|---|---|
| list targets | `org.ironlinux.AgentDesktops1.ListAgents` |
| run task | `SendInstruction(id, text)` |
| task finished | `AgentFinished(id, summary)` signal |
| needs approval | `ApprovalRequested(json)` → `Decide(request_id, allow)` |
| fetch results | `ListOutputs(id)` / `ExportOutput(id, path, dest)` |

Every call is polkit-authorised and ownership-checked by `iron-agentd`, so
Gnotch gains isolation without extra privileges. This connector belongs in the
Gnotch repository and has not been written.
