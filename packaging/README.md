# Linux packaging

Three install paths supported for the `obs-open-spark` plugin:

| Path | When to use | Built by |
|------|-------------|----------|
| `.rpm` | Fedora, RHEL, openSUSE, any rpm-based distro | CI (`plugin-build.yml`) via `fpm`; alt: `rpmbuild` from `rpm/obs-open-spark.spec` |
| `.deb` | Debian, Ubuntu, derivatives | CI (`plugin-build.yml`) via `fpm` |
| Flatpak extension (self-hosted) | Users running the official OBS Studio Flatpak (`com.obsproject.Studio`) | CI (`plugin-build.yml` → `flatpak` job) from `flatpak/com.obsproject.Studio.Plugin.OpenSpark.local.yml` |
| Flathub | Anyone — `flatpak install flathub com.obsproject.Studio.Plugin.OpenSpark` | Manual PR to `github.com/flathub/flathub` using the pinned-git manifest (see below) |
| `.tar` artifact | Manual / portable install | CI (default artifact, drop into `~/.config/obs-studio/plugins/`) |

## Install snippets

### RPM (Fedora / openSUSE / RHEL)

```bash
sudo dnf install ./obs-open-spark-*.rpm   # Fedora / RHEL
sudo zypper install ./obs-open-spark-*.rpm   # openSUSE
```

### Debian / Ubuntu

```bash
sudo apt install ./obs-open-spark_*.deb
```

### Flatpak (only if OBS itself is Flatpak)

```bash
flatpak install --user obs-open-spark.flatpak
```

The extension auto-mounts into `com.obsproject.Studio` under
`/app/plugins/OpenSpark/`.

### Portable / manual

```bash
mkdir -p ~/.config/obs-studio/plugins/obs-open-spark/bin/64bit
cp obs-open-spark.so ~/.config/obs-studio/plugins/obs-open-spark/bin/64bit/
mkdir -p ~/.config/obs-studio/plugins/obs-open-spark/data/locale
cp data/locale/*.ini ~/.config/obs-studio/plugins/obs-open-spark/data/locale/
```

## Building locally without CI

```bash
# rpm/deb via fpm
sudo gem install fpm
cmake -S plugin -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
DESTDIR=$PWD/stage cmake --install build
fpm -s dir -t rpm -n obs-open-spark -v 0.1.0 \
    --depends obs-studio --depends qt6-qtbase \
    -C stage usr

# native rpmbuild
tar czf ~/rpmbuild/SOURCES/obs-open-spark-0.1.0.tar.gz .
rpmbuild -ba packaging/rpm/obs-open-spark.spec

# flatpak (local build from the working tree)
flatpak-builder --user --install build-flatpak \
    packaging/flatpak/com.obsproject.Studio.Plugin.OpenSpark.local.yml
```

## Publishing to Flathub

Open Spark ships as an AppStream **addon** that extends the official OBS
Studio Flatpak. Flathub builds in a clean, network-isolated sandbox, so
the submission uses the pinned-git manifest
`flatpak/com.obsproject.Studio.Plugin.OpenSpark.yml` (not the `.local`
one) plus `plugin/com.obsproject.Studio.Plugin.OpenSpark.metainfo.xml`.

### One-time prep

1. Tag a release and push it: `git tag v0.1.0 && git push origin v0.1.0`.
2. Resolve the tag commit: `git rev-list -n 1 v0.1.0`.
3. URLs already point at `github.com/Mundo-Dev0ps/open-spark` in the
   manifest (`url:`) and the metainfo (three `<url>` entries) — change
   them only if the repo moves. Set the manifest `commit:` to the SHA
   from step 2. Confirm `runtime-version` matches current OBS:
   `flatpak info -m com.obsproject.Studio | grep runtime`.
4. Validate locally:
   ```bash
   appstreamcli validate --pedantic \
     plugin/com.obsproject.Studio.Plugin.OpenSpark.metainfo.xml
   flatpak run org.flatpak.Builder --force-clean \
     build-flathub packaging/flatpak/com.obsproject.Studio.Plugin.OpenSpark.yml
   flatpak run --command=flatpak-builder-lint org.flatpak.Builder \
     manifest packaging/flatpak/com.obsproject.Studio.Plugin.OpenSpark.yml
   ```

### Submit

1. Fork `github.com/flathub/flathub`, branch from `master` named
   `com.obsproject.Studio.Plugin.OpenSpark`.
2. Add the manifest as `com.obsproject.Studio.Plugin.OpenSpark.yml` at
   the repo root (the metainfo is pulled from our git source by the
   build — it does not go in the submission repo).
3. Open a PR. The Flathub bot builds it; a reviewer checks the addon
   extends `com.obsproject.Studio` and the metainfo validates.
4. On merge, Flathub creates a dedicated
   `flathub/com.obsproject.Studio.Plugin.OpenSpark` repo. Future
   releases = bump `tag`/`commit` there (optionally automated with
   `flatpak-external-data-checker`).

Install once published:

```bash
flatpak install flathub com.obsproject.Studio.Plugin.OpenSpark
```
