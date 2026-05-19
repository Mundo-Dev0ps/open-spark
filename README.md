<div align="center">

# ✨ Open Spark

### 🎙️ Build and tune your OBS scene by *talking to it*

Describe an overlay, a camera layout, a filter, or a whole scene in
plain language — a local LLM agent drives OBS and makes it happen.

🔒 Local-first &nbsp;·&nbsp; 🧠 LLM-agnostic &nbsp;·&nbsp; 🚫 No telemetry
&nbsp;·&nbsp; ☁️ No cloud &nbsp;·&nbsp; 🗝️ Keys stay on your machine

![status](https://img.shields.io/badge/status-early%20MVP-orange)
![license](https://img.shields.io/badge/license-MIT-blue)
![platform](https://img.shields.io/badge/OBS-30%2B-7e57c2)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/donjonny)

</div>

---

## ✨ What it does

- 💬 **Conversational agent inside OBS.** A docked chat panel (native Qt
  plugin, under *View → Docks → Open Spark*). Say *"add my webcam
  bottom-right with a chroma key and a neon frame, then a countdown
  top-center"* → it does it: camera, transforms, filters, audio,
  record/stream control, scene presets, and HTML overlays.
- 🎨 **Natural-language overlays.** The LLM writes HTML/CSS/JS, the
  backend serves it locally, OBS picks it up as a Browser Source.
- 🛡️ **Safe by default.** Destructive actions (delete a scene, …) run in
  *dry-run* and ask before applying.
- 🔌 **Bring your own model.** Anthropic, OpenAI, Gemini, Groq, Mistral,
  Cohere, DeepSeek, NVIDIA NIM, OpenRouter, or local Ollama / vLLM /
  LM Studio. 🆓 **Free options exist** (NVIDIA NIM credits, OpenRouter
  `:free`) — no paid key needed to try it.

---

## 🖼️ Screenshots

> 📸 _Drop PNGs into `docs/screenshots/` with these names and they render
> here. See `docs/screenshots/README.md` for the shot list._

|  |  |
|:--:|:--:|
| ![Agent dock](docs/screenshots/agent-dock.png) | ![Generated overlay](docs/screenshots/overlay.png) |
| **Agent chat dock** — talk, it builds | **A generated overlay live in OBS** |
| ![Slash shortcuts](docs/screenshots/slash.png) | ![Settings](docs/screenshots/settings.png) |
| **`/` shortcuts** | **Settings + model validation** |

---

## 🧩 Install

> Open Spark = a **native OBS plugin** (the dock) + a small **local
> backend** it talks to over loopback. Install the plugin one of the two
> ways below, then start the backend.

### 1️⃣ Plugin — Flatpak _(recommended)_

For OBS installed as a Flatpak. Open Spark ships as an addon that
extends `com.obsproject.Studio`:

```bash
# Flathub (once published)
flatpak install flathub com.obsproject.Studio.Plugin.OpenSpark

# …or a self-hosted bundle from GitHub Releases
flatpak install --user obs-open-spark.flatpak
```

### 1️⃣ Plugin — Manual _(native OBS install)_

Grab the artifact for your OS from
[**Releases**](https://github.com/Mundo-Dev0ps/open-spark/releases) and
drop it into OBS's plugin directory:

**🐧 Linux**

```bash
# Fedora / RHEL / openSUSE
sudo dnf install ./obs-open-spark-*.rpm
# Debian / Ubuntu
sudo apt install ./obs-open-spark_*.deb
# Portable (any distro): unpack the .tar.gz into
~/.config/obs-studio/plugins/obs-open-spark/
```

**🪟 Windows** — unzip `obs-open-spark-windows-x86_64.zip` so you get:

```
%APPDATA%\obs-studio\plugins\obs-open-spark\bin\64bit\obs-open-spark.dll
%APPDATA%\obs-studio\plugins\obs-open-spark\data\
```

(or drop it into `C:\Program Files\obs-studio\obs-plugins\64bit\`).

**🍎 macOS** — unpack the tarball into:

```
~/Library/Application Support/obs-studio/plugins/obs-open-spark.plugin
```

### 2️⃣ Backend

The agent needs the local backend running (FastAPI on
`127.0.0.1:8765`). Cross-platform via Python 3.11+:

```bash
# Linux / macOS
pipx install open-spark        # or: pip install --user open-spark
open-spark                     # serves the agent on :8765
```

```powershell
# Windows (PowerShell)
py -m pip install --user open-spark
py -m open_spark               # serves the agent on :8765
```

> 🐳 Prefer containers, or hacking on the code? A Docker Compose stack is
> provided **for development & test** — see
> [🛠️ Development & test](#️-development--test).

### 3️⃣ Wire it up

Open OBS → **View → Docks → Open Spark**, drag it beside the canvas.
Two tabs: **Agent** (chat) and **Settings**.

✅ `obs-websocket` is auto-configured by the plugin — no manual setup.

---

## 🤖 Configure LLM

Set a key + model in the dock **Settings** tab (stored in your OS
keyring), or via env. Pick a `provider/model` id:

| Provider | Where | Model id example |
|---|---|---|
| 🟢 NVIDIA NIM | build.nvidia.com (free credits) | `nvidia_nim/meta/llama-3.3-70b-instruct` |
| 🔀 OpenRouter | openrouter.ai (`:free` tier) | `openrouter/qwen/qwen-2.5-coder-32b-instruct:free` |
| 🟣 Anthropic | console.anthropic.com | `anthropic/claude-sonnet-4-6` |
| ⚪ OpenAI | platform.openai.com | `openai/gpt-4o` |
| 🏠 Ollama (local) | self-hosted | `ollama/llama3.1` (+ `OPENSPARK_LLM_BASE_URL`) |

🆓 **No paid key?** Step-by-step to generate free tokens (NVIDIA NIM,
OpenRouter, Groq, Gemini) → [`docs/llm-tokens.md`](docs/llm-tokens.md).

⚠️ **The agent needs a tool/function-calling model.** Settings validates
your pick and suggests known-good ones. Plain overlay generation works
on any model.

---

## 💬 Using the agent

Type what you want in the **Agent** tab. `/` shortcuts run locally and
never hit the LLM:

| Command | Action |
|---|---|
| `/help` | 📖 list shortcuts |
| `/clear` (`/new`, `/reset`) | 🧹 wipe the conversation |
| `/undo` | ↩️ remove inputs the agent added last turn |
| `/dry [on\|off]` | 🛡️ toggle dry-run (no arg = flip) |
| `/tools` | 🧰 list everything the agent can do |
| `/status` | 📡 backend + OBS connection state |

The agent acts only on your **most recent** message and on exactly the
targets you name. Destructive actions need confirmation unless dry-run
is off.

---

## 📦 Packaging & Flathub

CI builds artifacts on `v*` tags:

- 🟥 `.rpm` / 🟦 `.deb` — `packaging/rpm/obs-open-spark.spec` (fpm)
- 📦 Flatpak extension —
  `packaging/flatpak/com.obsproject.Studio.Plugin.OpenSpark*.yml`

**Flathub** ships as an addon extending the OBS Studio Flatpak:

```bash
flatpak install flathub com.obsproject.Studio.Plugin.OpenSpark
```

Submission = manual PR to `flathub/flathub` — full steps in
[`packaging/README.md`](packaging/README.md).

---

## 🛠️ Development & test

> 🧪 **Local only.** The Docker Compose stack and `start.sh` are a dev
> convenience for hacking on the code and running tests — **not** the
> end-user install path. The container's OBS uses a portable config
> under `./.portable-obs/`; your real OBS is never touched.

```bash
git clone git@github.com:Mundo-Dev0ps/open-spark.git
cd open-spark
cp .env.compose.example .env     # set ONE provider key + model
./start.sh                       # build + run backend + OBS, follow logs
./start.sh smoke                 # quick health check (no OBS)
./start.sh test                  # pytest suite in-container
./start.sh plugin-reload         # rebuild plugin + restart OBS
./start.sh help                  # all subcommands
```

`.env` is gitignored — local testing only; production uses the keyring.

```
+--------------------------+   obs-websocket   +-----------------------+
|  OBS Studio              |<----------------->|  Open Spark backend   |
|  · Open Spark dock (Qt)  |       HTTP        |  FastAPI @127.0.0.1    |
|  · camera / filters /    |<----------------->|  agent + tool calling |
|    scenes / overlays     |                   |  LiteLLM (any model)  |
+--------------------------+                   |  secrets (env/keyring)|
                                               +-----------------------+
```

---

## 💛 Support & collaborate

Open Spark is free and MIT. If it saves you setup time, fuel it with a
coffee — or team up to build features:

<div align="center">

[![Ko-fi](https://img.shields.io/badge/Ko--fi-Buy%20me%20a%20coffee-FF5E5B?logo=ko-fi&logoColor=white&style=for-the-badge)](https://ko-fi.com/donjonny)

</div>

🤝 PRs, issues and ideas welcome — open a ticket or say hi on Ko-fi.

---

## 🗂️ Project layout

```
src/open_spark/
  main.py           FastAPI app + lifespan
  config.py         Settings ("OPENSPARK_" env prefix + JSON)
  agent.py          tool-calling agent loop + model validation
  tools.py          ~34 OBS tools (overlays, camera, filters, audio…)
  llm.py            LiteLLM wrapper, overlay prompts, style presets
  obs_client.py     obs-websocket client + MockOBSClient (tests)
  secrets_store.py  env / keyring secrets
  api/              FastAPI routers
plugin/             native Qt OBS plugin (C++/CMake) + metainfo
packaging/          rpm spec + Flatpak manifests + how-to
tests/              pytest suite (mock OBS)
start.sh            dev/test container stack launcher (local only)
```

API spec: `openapi.yaml` (kept in sync by CI). More in
[`docs/development.md`](docs/development.md).

---

<div align="center">

📄 **MIT** &nbsp;·&nbsp; made for streamers who'd rather talk than click

</div>
