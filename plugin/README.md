# obs-spark-libre — native OBS plugin

Thin native plugin that hosts the Spark Libre web UI as a real OBS dock
and forwards user actions to the external Python backend on
`http://127.0.0.1:8765`.

## Why a plugin (and not just a Custom Browser Dock)

* OBS builds without `BROWSER_PANEL_SUPPORT_ENABLED` (most distro PPAs)
  don't show **Custom Browser Docks**, blocking the embedded UI path.
* A real plugin uses Qt directly + `obs_frontend_add_dock_by_id`, so it
  works on every OBS 30+ build regardless of how `obs-browser` was
  compiled.
* Stays "hybrid": only the dock and (later) hotkeys/menu items are
  native; everything else (LLM, overlay store, scene templates) is in
  the Python backend.

## Layout

```
plugin/
├── CMakeLists.txt
├── data/locale/en-US.ini
└── src/
    ├── plugin-main.c     # OBS_DECLARE_MODULE, obs_module_load
    ├── spark-dock.hpp
    └── spark-dock.cpp    # Qt dock + QWebEngineView
```

## Local build (containerized)

We never touch the host's OBS install. Iteration:

```bash
./start.sh plugin-build      # compile in builder container, write .so to .portable-obs/plugins/64bit/
./start.sh plugin-reload     # plugin-build + restart the obs container
./start.sh logs obs | grep -i spark
```

When the OBS GUI comes back, you'll find the dock under
**`Docks → Spark Libre`** (top-level menu in OBS 32; older versions
under `View → Docks`).

## CI builds (Linux / Windows / macOS)

`.github/workflows/plugin-build.yml` runs the same CMake on the three
public GitHub-hosted runners and uploads per-platform artifacts:

* `obs-spark-libre-linux-x86_64`     → `obs-spark-libre.so`
* `obs-spark-libre-windows-x86_64`   → `obs-spark-libre.dll`
* `obs-spark-libre-macos-universal`  → `obs-spark-libre.plugin`

Drop the artifact into your OBS plugins directory:

| OS      | Path |
|---------|------|
| Linux   | `~/.config/obs-studio/plugins/obs-spark-libre/bin/64bit/obs-spark-libre.so` |
| Windows | `%APPDATA%\obs-studio\plugins\obs-spark-libre\bin\64bit\obs-spark-libre.dll` |
| macOS   | `~/Library/Application Support/obs-studio/plugins/obs-spark-libre.plugin` |

## Roadmap

* [x] Phase 1 — skeleton plugin loads, registers a Qt dock with embedded
      `QWebEngineView` pointing at `/ui/`.
* [ ] Phase 2 — menu entries under `Tools → Spark Libre` (Generate /
      Generate scene / Settings) that call the backend via libcurl.
* [ ] Phase 3 — configurable hotkeys (Generate-from-prompt, Inject-last,
      Toggle-dock).
* [ ] Phase 4 — direct libobs path (when the plugin is loaded, the
      backend can use the in-process API instead of obs-websocket for
      lower-latency source/scene CRUD).
