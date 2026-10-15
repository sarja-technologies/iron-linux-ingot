# Iron Linux archive keys

Public OpenPGP keys (binary `gpg --export`, `*.gpg`) trusted for the Iron
package source. They are concatenated into
`/usr/share/keyrings/iron-archive-keyring.gpg` by the `iron-archive-keyring`
package and used only through `Signed-By:` on the Iron source.

* **No production key exists yet.** When one is created (offline, on the
  release maintainer's machine — see `docs/UPDATES.md`), commit its *public*
  part here as `iron-archive-<year>.gpg`. Never commit a secret key.
* Development images: `build/ingot-build` adds the machine-local development
  key (`.work/keys`) to the builder's copy of this directory, so dev images
  trust the dev repository. Set `INGOT_TRUST_DEV_KEY=0` for release builds.
* Rotation: publish a keyring package containing old + new keys, sign with the
  new key once clients have upgraded, then drop the old key in a later release.
