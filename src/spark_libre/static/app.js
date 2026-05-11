(() => {
  const $ = (id) => document.getElementById(id);
  const promptEl = $("prompt");
  const titleEl = $("title");
  const widthEl = $("width");
  const heightEl = $("height");
  const styleEl = $("style");
  const generateBtn = $("generate");
  const injectBtn = $("inject");
  const previewEl = $("preview");
  const metaEl = $("meta");
  const statusEl = $("status");
  const overlayList = $("overlay-list");

  let lastOverlayId = null;

  async function populateStyles() {
    try {
      const styles = await api("/api/styles");
      for (const target of [styleEl, $("scene-style")]) {
        if (!target) continue;
        for (const s of styles) {
          const opt = document.createElement("option");
          opt.value = s.key;
          opt.textContent = s.key.replaceAll("_", " ");
          opt.title = s.summary;
          target.appendChild(opt);
        }
      }
    } catch (_) {
      /* non-fatal */
    }
  }

  async function api(path, init = {}) {
    const opts = { headers: { "Content-Type": "application/json" }, ...init };
    const res = await fetch(path, opts);
    if (!res.ok) {
      const text = await res.text().catch(() => res.statusText);
      throw new Error(`${res.status} ${text}`);
    }
    return res.json();
  }

  function setStatus(text, kind = "") {
    statusEl.textContent = text;
    statusEl.className = "status" + (kind ? " " + kind : "");
  }

  async function refreshStatus() {
    try {
      const s = await api("/api/status");
      const obs = s.obs_connected
        ? (s.mock_obs ? "OBS: mock" : "OBS: connected")
        : "OBS: offline";
      const llm = s.has_default_llm_key ? "LLM: ready" : "LLM: no key";
      setStatus(`${obs} · ${llm} · ${s.default_model}`,
        s.obs_connected && s.has_default_llm_key ? "ok" : "warn");
    } catch (e) {
      setStatus("backend offline", "err");
    }
  }

  function renderHTML(html) {
    // charset=utf-8 in the MIME type matters: blob: URLs don't have HTTP
    // headers, so without this the iframe falls back to the platform
    // default and accented chars (ó, ñ, ¡) render as mojibake.
    const blob = new Blob([html], { type: "text/html;charset=utf-8" });
    previewEl.src = URL.createObjectURL(blob);
  }

  async function refreshOverlays() {
    try {
      const overlays = await api("/api/overlays");
      overlayList.innerHTML = "";
      for (const o of overlays) {
        const li = document.createElement("li");
        li.innerHTML = `
          <div class="title"></div>
          <div class="sub"></div>
          <div class="actions">
            <button class="secondary" data-act="preview">Preview</button>
            <button data-act="inject">Inject</button>
            <button class="secondary" data-act="refine" title="Iterative edit">Refine…</button>
            <button class="secondary" data-act="regenerate">Regenerate</button>
            <button class="secondary" data-act="delete">Delete</button>
          </div>`;
        li.querySelector(".title").textContent = o.title || o.slug;
        li.querySelector(".sub").textContent = `${o.model} · ${o.id}`;
        li.querySelector('[data-act="preview"]').onclick = () => {
          fetch(o.url).then((r) => r.text()).then(renderHTML);
          lastOverlayId = o.id;
          injectBtn.disabled = false;
        };
        li.querySelector('[data-act="inject"]').onclick = () => doInject(o.id);
        li.querySelector('[data-act="refine"]').onclick = () => doRefine(o.id);
        li.querySelector('[data-act="regenerate"]').onclick = () => doRegenerate(o.id);
        li.querySelector('[data-act="delete"]').onclick = async () => {
          if (!confirm(`Delete ${o.title}?`)) return;
          await api(`/api/overlays/${o.id}`, { method: "DELETE" });
          refreshOverlays();
        };
        overlayList.appendChild(li);
      }
    } catch (e) {
      console.error(e);
    }
  }

  async function doGenerate() {
    const prompt = promptEl.value.trim();
    if (!prompt) return;
    generateBtn.disabled = true;
    metaEl.textContent = "Generating...";
    try {
      const out = await api("/api/generate", {
        method: "POST",
        body: JSON.stringify({
          prompt,
          title: titleEl.value || null,
          width: parseInt(widthEl.value, 10) || 1920,
          height: parseInt(heightEl.value, 10) || 1080,
          style: styleEl.value || null,
        }),
      });
      lastOverlayId = out.overlay_id;
      renderHTML(out.html);
      metaEl.textContent = `id=${out.overlay_id} · model=${out.model} · ${out.url}`;
      injectBtn.disabled = false;
      refreshOverlays();
    } catch (e) {
      metaEl.textContent = "Error: " + e.message;
    } finally {
      generateBtn.disabled = false;
    }
  }

  async function doRefine(overlayId) {
    const instruction = prompt(
      "Refine: describe the change (e.g. 'make the background darker, shrink the chat box')"
    );
    if (instruction === null || !instruction.trim()) return;
    metaEl.textContent = `Refining ${overlayId}…`;
    try {
      const r = await api(`/api/overlays/${overlayId}/refine`, {
        method: "POST",
        body: JSON.stringify({
          instruction,
          style: styleEl.value || null,
        }),
      });
      lastOverlayId = r.overlay_id;
      const fresh = await fetch(`${r.url}?t=${Date.now()}`).then((x) => x.text());
      renderHTML(fresh);
      metaEl.textContent = `Refined ${r.overlay_id} · ${r.model}` +
        (r.obs_action ? ` · OBS ${r.obs_action}` : "");
      refreshOverlays();
    } catch (e) {
      metaEl.textContent = "Refine error: " + e.message;
    }
  }

  async function doRegenerate(overlayId) {
    const newPrompt = prompt(
      "New prompt? (leave empty to reuse the original prompt with the current style)",
      ""
    );
    // user pressed Cancel
    if (newPrompt === null) return;
    metaEl.textContent = `Regenerating ${overlayId}…`;
    try {
      const r = await api(`/api/overlays/${overlayId}/regenerate`, {
        method: "POST",
        body: JSON.stringify({
          prompt: newPrompt || null,
          style: styleEl.value || null,
        }),
      });
      lastOverlayId = r.overlay_id;
      // Force preview reload (URL is the same; cache-bust client-side).
      const fresh = await fetch(`${r.url}?t=${Date.now()}`).then((x) => x.text());
      renderHTML(fresh);
      metaEl.textContent = `Regenerated ${r.overlay_id} · ${r.model}` +
        (r.obs_action ? ` · OBS ${r.obs_action}` : "");
      refreshOverlays();
    } catch (e) {
      metaEl.textContent = "Regenerate error: " + e.message;
    }
  }

  async function doInject(overlayId) {
    const id = overlayId || lastOverlayId;
    if (!id) return;
    injectBtn.disabled = true;
    try {
      const r = await api("/api/inject", {
        method: "POST",
        body: JSON.stringify({ overlay_id: id }),
      });
      metaEl.textContent =
        `Injected → scene="${r.scene}" source="${r.name}" ${r.mock ? "(MOCK)" : ""}`;
    } catch (e) {
      metaEl.textContent = "Inject error: " + e.message;
    } finally {
      injectBtn.disabled = false;
    }
  }

  generateBtn.addEventListener("click", doGenerate);
  injectBtn.addEventListener("click", () => doInject());

  const deleteAllBtn = $("delete-all-overlays");
  if (deleteAllBtn) {
    deleteAllBtn.addEventListener("click", async () => {
      const list = await api("/api/overlays").catch(() => []);
      if (!list.length) {
        metaEl.textContent = "No overlays to delete.";
        return;
      }
      if (!confirm(`Delete ALL ${list.length} overlays? This cannot be undone.`)) {
        return;
      }
      deleteAllBtn.disabled = true;
      try {
        const r = await api("/api/overlays", { method: "DELETE" });
        metaEl.textContent = `Deleted ${r.deleted_count} overlays.`;
        lastOverlayId = null;
        injectBtn.disabled = true;
        previewEl.src = "about:blank";
        refreshOverlays();
      } catch (e) {
        metaEl.textContent = "Delete-all error: " + e.message;
      } finally {
        deleteAllBtn.disabled = false;
      }
    });
  }

  // --- Scene templates ------------------------------------------------------
  const scenePromptEl = $("scene-prompt");
  const sceneNameEl = $("scene-name");
  const sceneWidthEl = $("scene-width");
  const sceneHeightEl = $("scene-height");
  const sceneReplaceEl = $("scene-replace");
  const sceneGenerateBtn = $("scene-generate");
  const sceneMetaEl = $("scene-meta");
  const sceneSourcesEl = $("scene-sources");

  async function doGenerateScene() {
    const prompt = scenePromptEl.value.trim();
    if (!prompt) return;
    sceneGenerateBtn.disabled = true;
    sceneMetaEl.textContent = "Generating scene… (multi-source LLM call, can take ~20s)";
    sceneSourcesEl.innerHTML = "";
    try {
      const r = await api("/api/scenes/templates", {
        method: "POST",
        body: JSON.stringify({
          prompt,
          scene_name: sceneNameEl.value || null,
          canvas_width: parseInt(sceneWidthEl.value, 10) || 1920,
          canvas_height: parseInt(sceneHeightEl.value, 10) || 1080,
          replace: !!sceneReplaceEl.checked,
          style: ($("scene-style") && $("scene-style").value) || null,
        }),
      });
      sceneMetaEl.textContent =
        `Scene "${r.scene}" · ${r.sources.length} sources · model=${r.model}` +
        (r.mock ? " (MOCK)" : "");
      for (const s of r.sources) {
        const li = document.createElement("li");
        li.innerHTML = `
          <div class="title"></div>
          <div class="sub"></div>`;
        li.querySelector(".title").textContent = `${s.role} · ${s.name}`;
        const t = s.transform;
        li.querySelector(".sub").textContent =
          `${t.width}×${t.height} @ (${t.x},${t.y}) · ${s.url}`;
        sceneSourcesEl.appendChild(li);
      }
      refreshOverlays();
    } catch (e) {
      sceneMetaEl.textContent = "Error: " + e.message;
    } finally {
      sceneGenerateBtn.disabled = false;
    }
  }

  sceneGenerateBtn.addEventListener("click", doGenerateScene);

  populateStyles();
  refreshStatus();
  refreshOverlays();
  setInterval(refreshStatus, 5000);
})();
