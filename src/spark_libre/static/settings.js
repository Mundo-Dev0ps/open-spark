(() => {
  const $ = (id) => document.getElementById(id);
  const statusEl = $("status");

  async function api(path, init = {}) {
    const opts = { headers: { "Content-Type": "application/json" }, ...init };
    const res = await fetch(path, opts);
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    return res.json();
  }

  function setStatus(t, k) {
    statusEl.textContent = t;
    statusEl.className = "status" + (k ? " " + k : "");
  }

  async function load() {
    try {
      const s = await api("/api/settings");
      // Pre-fill from default_model "<provider>/<model>"
      const model = s.default_model || "";
      const slash = model.indexOf("/");
      if (slash > 0) {
        $("provider").value = model.slice(0, slash);
        $("model").value = model.slice(slash + 1);
      } else {
        $("model").value = model;
      }
      $("base-url").value = s.llm_base_url || "";
      $("obs-host").value = s.obs_host || "127.0.0.1";
      $("obs-port").value = s.obs_port || 4455;
      $("obs-scene").value = s.obs_scene_name || "Spark Libre";
      $("providers-with-key").textContent =
        "Providers with key stored: " +
        (s.providers_with_key.length ? s.providers_with_key.join(", ") : "none");
      setStatus("loaded", "ok");
    } catch (e) {
      setStatus("backend offline", "err");
    }
  }

  $("save-llm").addEventListener("click", async () => {
    const provider = $("provider").value;
    const model = $("model").value.trim();
    const apiKey = $("api-key").value;
    const baseUrl = $("base-url").value.trim();

    try {
      if (apiKey) {
        await api("/api/secrets", {
          method: "POST",
          body: JSON.stringify({ kind: "llm", provider, value: apiKey }),
        });
        $("api-key").value = "";
      }
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({
          default_model: model ? `${provider}/${model}` : null,
          llm_base_url: baseUrl || null,
        }),
      });
      setStatus("saved", "ok");
      load();
    } catch (e) {
      setStatus("error: " + e.message, "err");
    }
  });

  $("save-obs").addEventListener("click", async () => {
    const host = $("obs-host").value.trim();
    const port = parseInt($("obs-port").value, 10);
    const password = $("obs-password").value;
    const scene = $("obs-scene").value.trim();

    try {
      if (password) {
        await api("/api/secrets", {
          method: "POST",
          body: JSON.stringify({ kind: "obs", value: password }),
        });
        $("obs-password").value = "";
      }
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({
          obs_host: host,
          obs_port: port,
          obs_scene_name: scene,
        }),
      });
      setStatus("saved (restart Spark Libre to reconnect OBS)", "ok");
    } catch (e) {
      setStatus("error: " + e.message, "err");
    }
  });

  load();
})();
