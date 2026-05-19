# 🆓 Getting free LLM API keys

Open Spark works with any LiteLLM provider. You do **not** need a paid
key — this guide walks each free option, what you get, and the exact
`OPENSPARK_DEFAULT_MODEL` + env var to set.

Where to put the key:

- **Dock → Settings tab** → paste key + model → *Save* (stored in your
  OS keyring). Easiest, no files.
- **or `.env`** (dev/test only — gitignored): set the provider env var +
  `OPENSPARK_DEFAULT_MODEL`. See `.env.compose.example`.

> ⚠️ The **agent** needs a tool/function-calling model. Picks below are
> tool-capable. Plain overlay generation works on any model.

---

## 🟢 NVIDIA NIM — free credits (recommended)

Best free option: generous credits, strong tool-calling models.

1. Go to <https://build.nvidia.com/>.
2. Sign in (free NVIDIA account / Google / GitHub).
3. Pick a model, e.g. **Llama 3.3 70B Instruct**.
4. Click **Get API Key** (or **Build with this NIM → Get API Key**).
5. Copy the key — format `nvapi-...`.

```bash
NVIDIA_NIM_API_KEY=nvapi-xxxxxxxx
OPENSPARK_DEFAULT_MODEL=nvidia_nim/meta/llama-3.3-70b-instruct
# also good: nvidia_nim/qwen/qwen2.5-coder-32b-instruct
```

---

## 🔀 OpenRouter — free model tier

Aggregator. Some models are fully free (tagged `:free`).

1. Go to <https://openrouter.ai/> → sign up.
2. **Keys** → **Create Key**. Copy — format `sk-or-...`.
3. Use a model whose id ends in `:free`.

```bash
OPENROUTER_API_KEY=sk-or-xxxxxxxx
OPENSPARK_DEFAULT_MODEL=openrouter/qwen/qwen-2.5-coder-32b-instruct:free
```

> Free models rate-limit hard. If the agent stalls, retry or switch to
> NVIDIA NIM.

---

## ⚡ Groq — free tier, very fast

1. Go to <https://console.groq.com/> → sign in.
2. **API Keys** → **Create API Key**. Copy — format `gsk_...`.

```bash
GROQ_API_KEY=gsk_xxxxxxxx
OPENSPARK_DEFAULT_MODEL=groq/llama-3.3-70b-versatile
```

---

## 🔷 Google Gemini — free tier

1. Go to <https://aistudio.google.com/apikey>.
2. **Create API key** (free-tier project). Copy the key.

```bash
GEMINI_API_KEY=xxxxxxxx
OPENSPARK_DEFAULT_MODEL=gemini/gemini-2.0-flash
```

---

## 🏠 Ollama / vLLM / LM Studio — fully local, no key

Run a model on your own machine. No token, no quota.

1. Install Ollama (<https://ollama.com/>), then `ollama pull llama3.1`.
2. Point Open Spark at the local endpoint:

```bash
OPENSPARK_DEFAULT_MODEL=ollama/llama3.1
OPENSPARK_LLM_BASE_URL=http://127.0.0.1:11434
```

> Small local models often **fail tool-calling**. Use a 70B-class model
> or a hosted free option above for the agent.

---

## 💲 DeepSeek — cheap, not free

No free tier, but very low pay-as-you-go cost.

1. <https://platform.deepseek.com/> → sign up → **API keys** → create.

```bash
DEEPSEEK_API_KEY=sk-xxxxxxxx
OPENSPARK_DEFAULT_MODEL=deepseek/deepseek-chat
```

---

## Quick pick

| Need | Use |
|---|---|
| Best free, reliable agent | 🟢 NVIDIA NIM |
| Zero signup friction, fast | ⚡ Groq |
| Totally offline / private | 🏠 Ollama (70B) |
| Many models, one key | 🔀 OpenRouter `:free` |

After setting the key, in the dock **Settings** tab the model field
shows a ✅/❌ tool-calling badge. ❌ → pick another from this list.
