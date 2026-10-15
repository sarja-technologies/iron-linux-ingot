# Updates for Iron Linux's own packages

Ubuntu packages (kernel, GNOME, libraries, security fixes) keep coming from
Ubuntu's signed archives, and Firefox from Mozilla's. This document covers the
*third* source: the Iron packages built from this repository (`iron-*`,
`ingot-*`, and `gnotch`, which Iron packages from a pinned commit).

## Pieces

| Piece | Where | Role |
|---|---|---|
| `tools/ingot-publish` | maintainer machine | builds the signed repository tree |
| `iron-archive-keyring` (package) | installed systems | the public key(s) trusted for the Iron source |
| `iron-update` (in `iron-base-files`) | installed systems | configure, verify, list versions, roll back |
| `/etc/apt/sources.list.d/iron.sources` | installed systems | the source, `Signed-By:` the Iron keyring only |
| `/etc/apt/preferences.d/iron-archive.pref` | installed systems | pin: the source may supply only Iron packages |

## Trust model

* **Signatures.** `InRelease`/`Release.gpg` are signed (Ed25519 + SHA-512);
  `Release` carries SHA-256 sums of every index, and each index the SHA-256 of
  every package. APT verifies the whole chain; `ingot-publish verify` checks the
  same chain on the maintainer side before upload.
* **Scoped key.** The Iron key is trusted *only* for the Iron source
  (`Signed-By:`), never added to APT's global trust. It cannot sign Ubuntu
  packages.
* **Scoped packages.** Even with a validly signed index, the Iron source can
  only supply packages matching `iron-* ingot-* gnotch`; every other package it
  lists gets pin priority −1 (never installable). Tested with a hostile index
  that offered `bash 999.0` and `ironic-evil` (see "Validation").
* **Transport.** HTTPS is recommended for privacy and freshness but not relied
  on for integrity. Plain HTTP is accepted because signatures cover integrity.
* **Freeze/replay.** `ingot-publish --valid-days N` adds `Valid-Until`, so
  clients reject stale indexes; it requires re-signing (`resign`) at least every
  N days. Off by default until there is a publishing schedule to honour it.

## Versioning and compatibility

* Every build gets a strictly increasing version
  (`26.10~devN+t<UTC timestamp>` during development; releases drop `+t…`).
  `ingot-publish add` **refuses** a version that is not newer than the newest
  published one, and refuses to replace a published file with different
  content. A rebuilt package always needs a new version.
* All binaries of the `iron-ingot` source depend on each other with
  `= ${source:Version}` where they must move together, so APT upgrades (and
  rolls back) them as a set.
* Package maintainer scripts must keep upgrades from any earlier published
  version working: diversions (`iron-base-files`), the GDM theme alternative
  (`iron-shell`), schemas and dconf databases are re-applied idempotently.

## Rollback

* The repository keeps the newest `--keep` versions (default 5) of each package
  in its indexes; older files stay in `pool/`.
* `iron-update versions` lists what is available;
  `sudo iron-update rollback VERSION` shows the plan (all installed Iron
  packages to `VERSION` together, via `apt-get --allow-downgrades`) and applies
  it only with `--yes`.
* A bad release is withdrawn with `ingot-publish yank PACKAGE VERSION`: it
  disappears from the indexes (no new installs) but stays in `pool/`; its
  version number can never be reused.

## Publishing (maintainer)

```sh
# once, offline: create the production key and commit only its public half
gpg --homedir ~/iron-archive-key --quick-gen-key "Iron Linux archive" ed25519 sign 3y
gpg --homedir ~/iron-archive-key --export > packaging/archive-keys/iron-archive-2026.gpg

# each release
sudo INGOT_TRUST_DEV_KEY=0 build/ingot-build --arch amd64 packages     # builds the .debs
tools/ingot-publish --repo ~/iron-apt --gnupghome ~/iron-archive-key add .work/builder-amd64/src/*.deb
tools/ingot-publish --repo ~/iron-apt verify --keyring packaging/archive-keys/iron-archive-2026.gpg
rsync -a --delete-after ~/iron-apt/ <static host>        # any static HTTP(S) host
```

Images built with `INGOT_APT_URL=<url>` get the source pre-configured
(`iron-update set-source` runs at build time); otherwise users can run
`sudo iron-update set-source <url>`.

## Deployment blocker

The client and publishing workflow is implemented and was validated locally
(see "Validation"). What does not exist yet, and cannot be created from this
workspace without the owner:

1. **A public static host** for the repository tree (for example a public
   GitHub Pages repository, an S3/R2 bucket, or any web server). The Ingot
   GitHub repository is private, and GitHub Pages for private repositories
   needs a paid plan; the account's GitHub Actions are currently blocked by
   billing as well.
2. **A production signing key** generated and kept offline by the release
   maintainer. Development images trust only this machine's development key
   (`.work/keys`, never committed), so they cannot be used as release images.

Until both exist, installed systems print "Iron package source: not
configured" in `iron-update status`, and receive Ubuntu and Mozilla updates
only.

## Validation

See `docs/STATUS.md` → "Updates" for what was exercised and the evidence.
