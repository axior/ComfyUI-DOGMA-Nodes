import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// Separate event, routes and DOM. No changes to the phase-3 chooser or progress bar.
let active = null;
let dialog = null;
let reopen = null;
function element(tag, text, parent) {
  const el = document.createElement(tag);
  if (text != null) el.textContent = text;
  parent?.appendChild(el);
  return el;
}
function closeSigns() {
  dialog?.remove(); reopen?.remove(); active = null; dialog = null; reopen = null;
}
function showSigns(payload) {
  if (!payload?.token || !Array.isArray(payload.items) || active?.token === payload.token) return;
  closeSigns(); active = payload;
  dialog = element("dialog", null, document.body);
  Object.assign(dialog.style, {width: "min(1450px,94vw)", maxHeight: "90vh", overflow: "auto", padding: "24px", background: "#20252b", color: "#f3f4f6", border: "1px solid #617285", borderRadius: "12px"});
  element("h2", "Insegne e scritte - Milano anni 70", dialog);
  element("p", "Ogni scheda e un singolo elemento. A sinistra l'originale, a destra la maschera in azzurro. Controlla la maschera e modifica il prompt: cambieranno soltanto i pixel della zona indicata. Le proposte automatiche possono sbagliare.", dialog);
  const grid = element("div", null, dialog);
  Object.assign(grid.style, {display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,430px),1fr))", gap: "16px"});
  const entries = [];
  for (const item of payload.items) {
    const card = element("div", null, grid);
    Object.assign(card.style, {padding: "12px", border: "2px solid #53606d", borderRadius: "8px"});
    const label = element("label", null, card);
    const check = element("input", null, label); check.type = "checkbox"; check.checked = !!item.selected;
    check.setAttribute("aria-label", `Seleziona elemento ${item.id}`);
    element("strong", ` ${item.id}. ${item.name}`, label);
    const img = element("img", null, card);
    const params = new URLSearchParams({filename: item.image.filename, subfolder: item.image.subfolder || "", type: item.image.type || "temp"});
    img.src = api.apiURL(`/view?${params}`); img.alt = "Originale e maschera dell'elemento";
    Object.assign(img.style, {width: "100%", display: "block", marginTop: "8px"});
    element("p", item.reason, card);
    if (item.proposed_text) element("p", `Testo proposto: ${item.proposed_text}`, card);
    element("label", "Prompt modificabile per questo elemento", card);
    const prompt = element("textarea", null, card); prompt.value = item.prompt || ""; prompt.maxLength = 5000;
    prompt.setAttribute("aria-label", `Prompt elemento ${item.id}`);
    Object.assign(prompt.style, {boxSizing: "border-box", width: "100%", minHeight: "160px", resize: "vertical", padding: "10px", color: "#f3f4f6", background: "#171c21"});
    entries.push({id: item.id, check, prompt});
    check.onchange = () => {card.style.borderColor = check.checked ? "#6bc5c1" : "#53606d"; update();};
    prompt.oninput = () => update();
  }
  const status = element("p", "", dialog);
  const controls = element("div", null, dialog);
  Object.assign(controls.style, {display: "flex", flexWrap: "wrap", gap: "10px", position: "sticky", bottom: "0", padding: "12px 0", background: "#20252b"});
  const all = element("button", "Seleziona tutte", controls);
  const none = element("button", "Deseleziona tutte", controls);
  const submit = element("button", "Applica gli inpaint selezionati", controls);
  const skip = element("button", "Conserva originale", controls);
  const hide = element("button", "Nascondi finestra", controls);
  const stop = element("button", "Interrompi esecuzione", controls);
  function update() {
    const chosen = entries.filter(e => e.check.checked);
    const incomplete = chosen.some(e => !e.prompt.value.trim());
    status.textContent = `${chosen.length} elementi selezionati.` + (incomplete ? " Scrivi il prompt per gli elementi selezionati." : "");
    submit.disabled = !chosen.length || incomplete;
  }
  all.onclick = () => {for (const e of entries) {e.check.checked = true; e.check.onchange();}};
  none.onclick = () => {for (const e of entries) {e.check.checked = false; e.check.onchange();}};
  async function send(items) {
    submit.disabled = true; skip.disabled = true;
    try {
      const response = await api.fetchApi("/dogma/signs125/select", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({token: payload.token, items})});
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.message || "Selezione non accettata");
      if (active?.token === payload.token) closeSigns();
    } catch (error) {update(); status.textContent = String(error.message || error); skip.disabled = false;}
  }
  submit.onclick = () => send(entries.filter(e => e.check.checked).map(e => ({id: e.id, prompt: e.prompt.value.trim()})));
  skip.onclick = () => send([]);
  reopen = element("button", "Riprendi scelta insegne", document.body);
  Object.assign(reopen.style, {display: "none", position: "fixed", right: "24px", bottom: "80px", zIndex: "100000", padding: "16px", background: "#2a625f", color: "white"});
  hide.onclick = () => {dialog.close(); reopen.style.display = "block";};
  reopen.onclick = () => {dialog.showModal(); reopen.style.display = "none";};
  dialog.addEventListener("cancel", e => {e.preventDefault(); hide.click();});
  stop.onclick = async () => {
    try {const r = await api.fetchApi("/interrupt", {method: "POST"}); if (!r.ok) throw new Error("Interruzione non riuscita"); closeSigns();}
    catch (e) {status.textContent = e.message;}
  };
  update(); dialog.showModal();
}
app.registerExtension({
  name: "DOGMA.Signs.v125",
  nodeCreated(node) {
    if (!/^DOGMASign(?:Plan|Prepare|Review|Render)V125$/.test(node.comfyClass || node.type || "")) return;
    const labels = {manual_mask: "MASCHERA MANUALE", manual_prompt: "PROMPT MANUALE", project_context: "CONTESTO / MILANO ANNI 70",
      vision_model: "MODELLO ANALISI", memory_mode: "GESTIONE MEMORIA", analysis_side: "LATO ANALISI", rerun: "RICALCOLA PROPOSTE",
      render_side: "LATO RENDER ELEMENTO", context_px: "CONTESTO INTORNO ALL'ELEMENTO", max_regions: "MAX ELEMENTI",
      sam_threshold: "SOGLIA SAM", min_confidence: "FIDUCIA MINIMA AUTOPROMPT", show_popup: "MOSTRA POPUP",
      steps: "PASSI", cfg: "CFG", sampler_name: "SAMPLER", scheduler: "SCHEDULER", denoise: "DENOISE",
      seed: "SEED", feather_px: "SFUMATURA INTERNA (PIXEL ORIGINALI)", negative_prompt: "PROMPT NEGATIVO", vae_tile_size: "VAE TILED (PIXEL)"};
    for (const widget of node.widgets || []) if (labels[widget.name]) widget.label = labels[widget.name];
  },
  setup() {
    api.addEventListener("dogma-signs125-choice", event => showSigns(event.detail));
    let polling = false;
    const pending = async () => {
      if (polling) return; polling = true;
      try {
        const response = await api.fetchApi("/dogma/signs125/pending");
        if (!response.ok) return;
        const data = await response.json();
        if (active && !data.items?.some(p => p.token === active.token)) closeSigns();
        if (!active && data.items?.length) showSigns(data.items[0]);
      } catch (_) {} finally {polling = false;}
    };
    api.addEventListener("reconnected", pending);
    pending(); setInterval(pending, 5000);
  }
});
