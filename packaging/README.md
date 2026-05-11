# Linux packaging

Three install paths supported for the `obs-spark-libre` plugin:

| Path | When to use | Built by |
|------|-------------|----------|
| `.rpm` | Fedora, RHEL, openSUSE, any rpm-based distro | CI (`plugin-build.yml`) via `fpm`; alt: `rpmbuild` from `rpm/obs-spark-libre.spec` |
| `.deb` | Debian, Ubuntu, derivatives | CI (`plugin-build.yml`) via `fpm` |
| Flatpak extension | Users running the official OBS Studio Flatpak (`com.obsproject.Studio`) | CI (`plugin-build.yml` → `flatpak` job) using `flatpak/com.sparklibre.Plugin.yml` |
| `.tar` artifact | Manual / portable install | CI (default artifact, drop into `~/.config/obs-studio/plugins/`) |

## Install snippets

### RPM (Fedora / openSUSE / RHEL)

```bash
sudo dnf install ./obs-spark-libre-*.rpm   # Fedora / RHEL
sudo zypper install ./obs-spark-libre-*.rpm   # openSUSE
```

### Debian / Ubuntu

```bash
sudo apt install ./obs-spark-libre_*.deb
```

### Flatpak (only if OBS itself is Flatpak)

```bash
flatpak install --user obs-spark-libre.flatpak
```

The extension auto-mounts into `com.obsproject.Studio` under
`/app/plugins/SparkLibre/`.

### Portable / manual

```bash
mkdir -p ~/.config/obs-studio/plugins/obs-spark-libre/bin/64bit
cp obs-spark-libre.so ~/.config/obs-studio/plugins/obs-spark-libre/bin/64bit/
mkdir -p ~/.config/obs-studio/plugins/obs-spark-libre/data/locale
cp data/locale/*.ini ~/.config/obs-studio/plugins/obs-spark-libre/data/locale/
```

## Building locally without CI

```bash
# rpm/deb via fpm
sudo gem install fpm
cmake -S plugin -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
DESTDIR=$PWD/stage cmake --install build
fpm -s dir -t rpm -n obs-spark-libre -v 0.1.0 \
    --depends obs-studio --depends qt6-qtbase \
    -C stage usr

# native rpmbuild
tar czf ~/rpmbuild/SOURCES/obs-spark-libre-0.1.0.tar.gz .
rpmbuild -ba packaging/rpm/obs-spark-libre.spec

# flatpak
flatpak-builder --user --install build-flatpak \
    packaging/flatpak/com.sparklibre.Plugin.yml
```
