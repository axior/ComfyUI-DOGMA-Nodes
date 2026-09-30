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
  element("h2", "Fase 3 — scegli le categorie da lavorare", dialog);
  element("p", "Controlla originale, maschera e sovrapposizione. Seleziona le categorie desiderate: le altre non verranno renderizzate. Le proposte automatiche possono essere sbagliate.", dialog);
  const grid = element("div", null, dialog);
  Object.assign(grid.style, { display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(420px,1fr))", gap: "16px" });
  const inputs = [];
  for (const category of payload.categories) {
    const card = element("label", null, grid);
    Object.assign(card.style, { display: "block", border: "2px solid #53606d", borderRadius: "8px", padding: "10px", cursor: "pointer" });
    const input = element("input", null, card); input.type = "checkbox"; inputs.push([input, category.id]);
    element("strong", ` ${category.id}. ${category.name}`, card);
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
    input.addEventListener("change", () => {
      input.checked ? selected.add(category.id) : selected.delete(category.id);
      card.style.borderColor = input.checked ? "#6bc5c1" : "#53606d";
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
      const response = await api.fetchApi("/dogma/categories/select", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: payload.token, indices }) });
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

app.registerExtension({
  name: "DOGMA.CategoryChoiceV111",
  async setup() {
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
