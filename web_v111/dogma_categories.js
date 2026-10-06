import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

let active = null;
let dialog = null;
let reopen = null;
let zoom = null;

function element(tag, text, parent) {
  const el = document.createElement(tag);
  if (text !== null) el.textContent = text;
  if (parent) parent.appendChild(el);
  return el;
}
function closeChoice(token) {
  if (active?.token !== token) return;
  dialog?.remove(); reopen?.remove(); zoom?.remove(); dialog = null; reopen = null; zoom = null; active = null;
}
function showChoice(payload) {
  if (!payload?.token || !Array.isArray(payload.categories)) return;
  if (active?.token === payload.token && dialog?.isConnected) return;
  dialog?.remove(); reopen?.remove(); active = payload;
  const selected = new Set();
  dialog = element("dialog", null, document.body);
  Object.assign(dialog.style, { width: "min(1400px,94vw)", maxHeight: "92vh", overflow: "auto", background: "#20252b", color: "#f3f4f6", border: "1px solid #617285", borderRadius: "12px", padding: "24px" });
  element("h2", "Fase 3 - scegli le categorie da lavorare", dialog);
  element("p", "Controlla originale, maschera e sovrapposizione. Seleziona le categorie desiderate: le altre non verranno renderizzate. Le proposte automatiche possono essere sbagliate.", dialog);
  const grid = element("div", null, dialog);
  Object.assign(grid.style, { display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(420px,1fr))", gap: "16px" });
  const inputs = [];
  const denoiseControls = new Map();
  const hasDenoise = Number.isFinite(payload.default_denoise);
  if (hasDenoise) element("p", `Denoise generale: ${payload.default_denoise.toFixed(2)}. Attiva un valore personalizzato solo per le categorie da modificare. 0 conserva i pixel originali.`, dialog);
  for (const category of payload.categories) {
    const card = element("div", null, grid);
    const label = element("label", null, card);
    Object.assign(card.style, { display: "block", border: "2px solid #53606d", borderRadius: "8px", padding: "10px", cursor: "pointer" });
    const input = element("input", null, label); input.type = "checkbox"; inputs.push([input, category.id]);
    element("strong", ` ${category.id}. ${category.name}`, label);
    const image = element("img", null, card);
    const params = new URLSearchParams({ filename: category.image.filename, subfolder: category.image.subfolder || "", type: category.image.type || "temp" });
    image.src = api.apiURL(`/view?${params}`); image.alt = `${category.name}: originale, maschera, sovrapposizione`;
    Object.assign(image.style, { display: "block", width: "100%", marginTop: "8px" });
    image.title = "Clicca per ingrandire originale, maschera e sovrapposizione";
    image.onclick = (event) => {
      event.preventDefault(); event.stopPropagation(); zoom?.remove();
      zoom = element("dialog", null, document.body);
      Object.assign(zoom.style, { width: "94vw", maxHeight: "94vh", overflow: "auto", background: "#20252b", color: "white", padding: "20px" });
      element("h3", `${category.id}. ${category.name}`, zoom);
      const close = element("button", "Torna alla scelta", zoom);
      const enlarged = element("img", null, zoom); enlarged.src = image.src; enlarged.alt = image.alt;
      Object.assign(enlarged.style, { width: "100%", display: "block", marginTop: "16px" });
      close.onclick = () => { zoom?.remove(); zoom = null; };
      zoom.addEventListener("cancel", (event) => { event.preventDefault(); close.click(); });
      zoom.showModal();
    };
    if (hasDenoise) {
      const row = element("div", null, card);
      Object.assign(row.style, { marginTop: "12px", display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap" });
      const customLabel = element("label", null, row);
      const custom = element("input", null, customLabel); custom.type = "checkbox";
      element("span", " Denoise personalizzato", customLabel);
      const slider = element("input", null, row); slider.type = "range";
      slider.min = "0"; slider.max = "1"; slider.step = "0.01"; slider.value = String(payload.default_denoise);
      slider.setAttribute("aria-label", `Denoise ${category.name}`);
      const value = element("output", null, row);
      const refresh = () => {
        custom.disabled = !input.checked;
        slider.disabled = !input.checked || !custom.checked;
        value.textContent = Number(custom.checked ? slider.value : payload.default_denoise).toFixed(2) + (custom.checked ? " personalizzato" : " generale");
      };
      custom.onchange = refresh; slider.oninput = refresh;
      denoiseControls.set(category.id, { custom, slider, refresh }); refresh();
    }
    input.addEventListener("change", () => {
      input.checked ? selected.add(category.id) : selected.delete(category.id);
      card.style.borderColor = input.checked ? "#6bc5c1" : "#53606d";
      denoiseControls.get(category.id)?.refresh();
      update();
    });
  }
  const controls = element("div", null, dialog);
  Object.assign(controls.style, { display: "flex", flexWrap: "wrap", gap: "12px", marginTop: "20px", alignItems: "center" });
  const status = element("p", "Nessuna categoria selezionata.", dialog);
  const all = element("button", "Seleziona tutte", controls);
  const none = element("button", "Deseleziona tutte", controls);
  const submit = element("button", "Lavora le categorie selezionate", controls); submit.disabled = true;
  const skip = element("button", "Salta tutti i render della fase 3", controls);
  const hide = element("button", "Nascondi finestra", controls);
  const stop = element("button", "Interrompi esecuzione", controls);
  function update() { submit.disabled = !selected.size; status.textContent = `${selected.size} categorie selezionate su ${payload.categories.length}.`; }
  all.onclick = () => inputs.forEach(([i]) => { i.checked = true; i.dispatchEvent(new Event("change")); });
  none.onclick = () => inputs.forEach(([i]) => { i.checked = false; i.dispatchEvent(new Event("change")); });
  async function send(indices) {
    submit.disabled = true; skip.disabled = true;
    try {
      const body = { token: payload.token, indices };
      if (hasDenoise) body.denoise_overrides = Object.fromEntries(indices.filter(id => denoiseControls.get(id)?.custom.checked).map(id => [String(id), Number(denoiseControls.get(id).slider.value)]));
      const response = await api.fetchApi("/dogma/categories/select", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.message || "Selezione non accettata");
      closeChoice(payload.token);
    } catch (error) { status.textContent = String(error.message || error); skip.disabled = false; submit.disabled = !selected.size; }
  }
  submit.onclick = () => send([...selected].sort((a,b) => a-b));
  skip.onclick = () => send([]);
  reopen = element("button", "Riprendi scelta categorie DOGMA", document.body);
  Object.assign(reopen.style, { display: "none", position: "fixed", right: "24px", bottom: "24px", zIndex: "100000", padding: "16px", background: "#2a625f", color: "white" });
  hide.onclick = () => { dialog.close(); reopen.style.display = "block"; };
  reopen.onclick = () => { dialog.showModal(); reopen.style.display = "none"; };
  dialog.addEventListener("cancel", (event) => { event.preventDefault(); hide.click(); });
  stop.onclick = async () => { await api.fetchApi("/interrupt", { method: "POST" }); closeChoice(payload.token); };
  dialog.showModal();
}

// rgthree's queue metadata is memory-only and can be absent after a reload.
// Adapt its visible fallback text, without modifying rgthree files or progress values.
function progressLabel(nodeId, prompt) {
  const id = String(nodeId ?? "");
  const exact = prompt?.[id];
  if (exact?._meta?.title || exact?.class_type) return exact._meta?.title || exact.class_type;
  const rootId = id.split(":")[0];
  const root = prompt?.[rootId];
  if (root?._meta?.title || root?.class_type) return root._meta?.title || root.class_type;
  const node = app.graph?.getNodeById?.(Number(rootId));
  return node?.title || node?.type || "Operazione in corso";
}

function readableProgress(text, label) {
  // Only recognize rgthree's running placeholders. Errors and real percentages stay intact.
  if (!/^\(\d+\)\s/.test(text)) return text;
  return text.replace(/^(\(\d+\)\s*)\?\?%/, "$1In esecuzione (totale non disponibile)")
    .replace(/ - \?\?\?(?=\s*\(|$)/, () => ` - ${label || "Operazione in corso"}`);
}

function installProgressDisplay() {
  if (typeof MutationObserver === "undefined") return;
  const installed = Symbol.for("DOGMA.progressDisplay.v123");
  if (globalThis[installed]) return;
  globalThis[installed] = true;
  const observed = new Map();
  let prompts = new Map();
  let soleRunningPrompt = null;
  let queueRead = null;
  let scanQueued = false;

  function update(bar) {
    const entry = observed.get(bar);
    if (!entry) return;
    const execution = bar.currentPromptExecution;
    const id = execution?.currentlyExecuting?.nodeId;
    const prompt = execution?.promptApi || prompts.get(execution?.id)
      || (execution?.id === "unknown" ? soleRunningPrompt : null);
    const text = entry.text.textContent || "";
    if (text !== entry.rendered) entry.raw = text;
    const readable = readableProgress(entry.raw ?? text, progressLabel(id, prompt));
    entry.rendered = readable;
    if (readable !== text) entry.text.textContent = readable;
  }

  function scan() {
    scanQueued = false;
    for (const [bar, entry] of observed) {
      if (!bar.isConnected) { entry.observer.disconnect(); observed.delete(bar); }
    }
    for (const bar of document.querySelectorAll("rgthree-progress-bar")) {
      const text = bar.shadowRoot?.querySelector('[part="text"]');
      if (!text || observed.get(bar)?.text === text) continue;
      observed.get(bar)?.observer.disconnect();
      const observer = new MutationObserver(() => update(bar));
      observed.set(bar, { text, observer });
      observer.observe(text, { childList: true, characterData: true, subtree: true });
      update(bar);
    }
  }
  function scheduleScan() {
    if (!scanQueued) { scanQueued = true; queueMicrotask(scan); }
  }
  async function recoverLabels() {
    if (queueRead) return queueRead;
    queueRead = (async () => {
      try {
        const response = await api.fetchApi("/queue", { cache: "no-store" });
        if (!response.ok) return;
        const data = await response.json();
        const next = new Map();
        for (const row of [...(data.queue_running || []), ...(data.queue_pending || [])]) {
          if (Array.isArray(row) && typeof row[1] === "string" && row[2] && typeof row[2] === "object") next.set(row[1], row[2]);
        }
        prompts = next;
        soleRunningPrompt = data.queue_running?.length === 1 ? data.queue_running[0][2] : null;
        for (const bar of observed.keys()) update(bar);
      } catch { /* Optional display enhancement: never interrupt a queue. */ }
    })();
    try { await queueRead; } finally { queueRead = null; }
  }

  const bodyObserver = new MutationObserver(scheduleScan);
  bodyObserver.observe(document.body, { childList: true, subtree: true });
  api.addEventListener("execution_start", recoverLabels);
  api.addEventListener("reconnected", recoverLabels);
  // Custom element may be upgraded after DOGMA's extension setup.
  globalThis.customElements?.whenDefined("rgthree-progress-bar").then(scheduleScan);
  scan();
  recoverLabels();
}

app.registerExtension({
  name: "DOGMA.CategoryChoiceV111",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "DOGMAReviewPairV123") return;
    const original = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (output) {
      original?.apply(this, arguments);
      const title = output?.dogma_review_label?.[0];
      if (!title) return;
      this.title = title;
      for (const slot of [0, 1]) {
        for (const id of this.outputs?.[slot]?.links || []) {
          const link = this.graph?.links?.[id];
          const comparer = this.graph?.getNodeById?.(link?.target_id);
          if (comparer?.type === "Image Comparer (rgthree)") comparer.title = title + " | A: prima / B: dopo";
        }
      }
      this.setDirtyCanvas?.(true, true);
    };
  },
  async setup() {
    installProgressDisplay();
    api.addEventListener("dogma-category-choice", (event) => showChoice(event.detail));
    api.addEventListener("dogma-category-choice-close", (event) => closeChoice(event.detail.token));
    // A browser reload while the queue is paused must not lose the pending choice.
    try {
      const response = await api.fetchApi("/dogma/categories/pending");
      const { items } = await response.json();
      if (items?.length) showChoice(items[0]);
    } catch (error) { console.warn("DOGMA category selection unavailable", error); }
  }
});
