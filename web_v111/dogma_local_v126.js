import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// Isolated UI: never touches the V81 or v125 dialogs, node IDs or widgets.
let active = null, dialog = null, reopen = null, localBusy = false;
const submitted = new Set();
function rememberSubmitted(token) {
  submitted.add(token);
  if(submitted.size>128)submitted.delete(submitted.values().next().value);
}
function el(tag, text, parent) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  parent?.appendChild(node);
  return node;
}
function closeLocal() {
  dialog?.remove(); reopen?.remove();
  dialog = null; reopen = null; active = null; localBusy = false;
}
function showLocal(payload) {
  if (!payload?.token || !Array.isArray(payload.items)) return;
  if(submitted.has(payload.token)||payload.phase==="render")return;
  if (active?.token === payload.token && active.revision >= payload.revision) return;
  const hidden = dialog && !dialog.open;
  closeLocal(); active = payload; localBusy = !!payload.busy;
  dialog = el("dialog", null, document.body);
  Object.assign(dialog.style, {width:"min(1000px,90vw)",maxHeight:"80vh",overflow:"auto",padding:"18px",background:"#20252b",color:"#f2f4f5",border:"1px solid #617285",borderRadius:"12px"});
  const close=el("button","Chiudi finestra (non interrompe)",dialog);
  Object.assign(close.style,{float:"right",padding:"8px"});
  el("h2", "Inpaint locale - descrivi ogni zona mascherata", dialog);
  if(payload.server_version!=="1.0.29") {
    const warning=el("p","ATTENZIONE: ComfyUI sta eseguendo una versione precedente dei nodi. Riavvia ComfyUI e ricarica questa pagina prima di usare il workflow V4.",dialog);
    Object.assign(warning.style,{background:"#713d17",padding:"12px",fontWeight:"bold"});
  } else el("p","DOGMA Inpaint 1.0.29 attivo",dialog);
  el("p", "A sinistra il ritaglio originale, a destra la zona modificabile in azzurro. Puoi indicare cosa deve diventare o scrivere un prompt manuale. Premi Applica: i prompt mancanti vengono preparati automaticamente. La zona azzurra include l’espansione impostata nel workflow. Ogni ritaglio viene lavorato a 2K con le impostazioni predefinite.", dialog);
  const grid = el("div", null, dialog);
  Object.assign(grid.style, {display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(min(100%,430px),1fr))",gap:"16px"});
  const entries = [], editable = [], actionButtons = [];
  const field = (tag, title, value, max, card, aria) => {
    el("label", title, card);
    const f = el(tag, null, card); f.value = value || ""; f.maxLength = max;
    f.setAttribute("aria-label", aria);
    Object.assign(f.style, {display:"block",boxSizing:"border-box",width:"100%",margin:"6px 0 12px",padding:"10px",background:"#151b20",color:"#f2f4f5",minHeight:tag==="textarea"?"100px":"36px"});
    editable.push(f); return f;
  };
  for (const item of payload.items) {
    const card = el("div", null, grid);
    Object.assign(card.style, {padding:"14px",border:"1px solid #687886",borderRadius:"8px"});
    const label = el("label", null, card);
    const check = el("input", null, label); check.type="checkbox"; check.checked=!!item.selected;
    check.setAttribute("aria-label", `Lavora zona ${item.id}`); editable.push(check);
    el("strong", ` ${item.label}`, label);
    const img = el("img", null, card);
    const params = new URLSearchParams({filename:item.preview.filename,subfolder:item.preview.subfolder||"",type:item.preview.type||"temp"});
    img.src=api.apiURL(`/view?${params}`); img.alt="Originale e maschera della zona";
    Object.assign(img.style,{width:"100%",maxHeight:"280px",objectFit:"contain",display:"block",margin:"12px 0"});
    const brief=field("textarea","Descrizione breve (facoltativa, da sviluppare automaticamente)",item.brief,2000,card,`Descrizione zona ${item.id}`);
    brief.placeholder="Es. cartello blu con freccia bianca diagonale verso destra in alto";
    const exact=field("textarea","Testo esatto (facoltativo)",item.exact_text,500,card,`Testo esatto zona ${item.id}`);
    exact.style.minHeight="55px";
    const improve=el("button","Migliora questo prompt",card); actionButtons.push(improve);
    const prompt=field("textarea","Prompt manuale / generato (facoltativo; se compilato viene usato direttamente)",item.prompt,6000,card,`Prompt finale zona ${item.id}`);
    prompt.style.minHeight="170px";
    if(item.error) el("p",item.error,card);
    const groupLabel=el("label",null,card);
    const group=el("input",null,groupLabel); group.type="checkbox";
    group.setAttribute("aria-label",`Unisci zona ${item.id}`); editable.push(group);
    el("span"," Unisci questa zona con altre selezionate per l'unione",groupLabel);
    const entry={id:item.id,check,brief,exact,prompt,group}; entries.push(entry);
    // Optional wording edits must never erase an existing prompt.
    brief.oninput=()=>{entry.briefChanged=true;update();}; exact.oninput=update;
    check.onchange=update; group.onchange=update; prompt.oninput=update;
    improve.onclick=()=>send("improve",[item.id]);
    entry.improve=improve;
  }
  const status=el("p",payload.message||"",dialog);
  const controls=el("div",null,dialog);
  Object.assign(controls.style,{display:"flex",flexWrap:"wrap",gap:"10px",position:"sticky",bottom:"0",padding:"12px 0",background:"#20252b"});
  const improveAll=el("button","Migliora prompt selezionati",controls);
  const selectAll=el("button","Seleziona tutti",controls);
  const deselectAll=el("button","Deseleziona tutti",controls);
  const merge=el("button","Unisci zone contrassegnate",controls);
  const apply=el("button","Applica inpaint selezionati",controls);
  const skip=el("button","Conserva originale",controls);
  const hide=el("button","Nascondi finestra",controls);
  const stop=el("button","Interrompi esecuzione",controls);
  actionButtons.push(improveAll,selectAll,deselectAll,merge,apply,skip);
  function snapshot(){return entries.map(e=>({id:e.id,selected:e.check.checked,brief:e.brief.value,exact_text:e.exact.value,prompt:e.prompt.value}));}
  function update(){
    const selected=entries.filter(e=>e.check.checked);
    for(const f of editable) f.disabled=localBusy;
    for(const b of actionButtons) b.disabled=localBusy;
    if(localBusy){status.textContent="Operazione in corso. Il popup si aggiornera al termine; puoi nasconderlo durante l'attesa.";return;}
    improveAll.disabled=!selected.length;
    merge.disabled=entries.filter(e=>e.group.checked).length<2;
    apply.disabled=!selected.length;
    const missing=selected.filter(e=>!e.prompt.value.trim()).map(e=>e.id);
    const changed=selected.filter(e=>e.briefChanged&&e.prompt.value.trim()).map(e=>e.id);
    status.textContent=`${selected.length} zone selezionate. `+(missing.length?`Preparazione automatica al clic su Applica per le zone: ${missing.join(', ')}. `:"")+(changed.length?`Descrizione cambiata nelle zone ${changed.join(', ')}: il prompt compilato ha precedenza; svuotalo per rigenerarlo automaticamente. `:"")+(payload.message||"");
  }
  async function send(action,ids=[]){
    if(localBusy)return;
    const finishing=action==="render"||action==="skip";
    if(finishing)rememberSubmitted(payload.token);
    localBusy=true;update();
    try{
      const r=await api.fetchApi("/dogma/local126/action",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token:payload.token,revision:payload.revision,action,items:snapshot(),ids})});
      const d=await r.json(); if(!r.ok||!d.ok)throw new Error(d.message||"Operazione non accettata");
      if(active?.token===payload.token&&active.revision===payload.revision&&(action==="render"||action==="skip"))closeLocal();
    }catch(error){
      if(finishing)submitted.delete(payload.token);
      if(active?.token===payload.token&&active.revision===payload.revision){localBusy=false;update();status.textContent=String(error.message||error);}
    }
  }
  improveAll.onclick=()=>send("improve",entries.filter(e=>e.check.checked).map(e=>e.id));
  selectAll.onclick=()=>{for(const e of entries)e.check.checked=true;update();};
  deselectAll.onclick=()=>{for(const e of entries)e.check.checked=false;update();};
  merge.onclick=()=>send("merge",entries.filter(e=>e.group.checked).map(e=>e.id));
  apply.onclick=()=>send("render");skip.onclick=()=>send("skip");
  reopen=el("button","Riprendi inpaint locale",document.body);
  Object.assign(reopen.style,{display:"none",position:"fixed",right:"24px",bottom:"135px",zIndex:"100000",padding:"15px",background:"#2a625f",color:"white"});
  hide.onclick=()=>{dialog.close();reopen.style.display="block";};
  close.onclick=hide.onclick;
  reopen.onclick=()=>{dialog.showModal();reopen.style.display="none";};
  dialog.addEventListener("cancel",e=>{e.preventDefault();hide.click();});
  stop.onclick=async()=>{try{const r=await api.fetchApi("/interrupt",{method:"POST"});if(!r.ok)throw new Error("Interruzione non riuscita");closeLocal();}catch(e){status.textContent=e.message;}};
  update();if(hidden)reopen.style.display="block";else dialog.showModal();
}
app.registerExtension({
  name:"DOGMA.Local.v126",
  nodeCreated(node){
    if(!/^DOGMALocal(?:Masks|Review|Render)V126$/.test(node.comfyClass||node.type||""))return;
    const labels={mask_expand_px:"ESPANSIONE MASCHERE (PX ORIGINALI)",match_photo:"INTEGRAZIONE FOTO",photo_strength:"INTENSITA INTEGRAZIONE",context_px:"CONTESTO INTORNO ALLA ZONA",render_side:"LATO LUNGO RITAGLIO",project_context:"CONTESTO DEL PROGETTO",rerun:"NUOVA REVISIONE",vision_model:"QWEN MIGLIORA PROMPT",memory_mode:"GESTIONE MEMORIA",mode:"MODALITA DENOISE / EDIT",denoise:"INTENSITA DENOISE (EDIT USA 1.00)",feather_px:"SFUMATURA BORDI - TUTTE LE MASCHERE",vae_tile_size:"VAE TILED",seed:"SEED",negative_prompt:"PROMPT NEGATIVO"};
    for(const w of node.widgets||[])if(labels[w.name])w.label=labels[w.name];
  },
  setup(){
    api.addEventListener("dogma-local126-review",e=>showLocal(e.detail));
    api.addEventListener("dogma-local126-closed",e=>{rememberSubmitted(e.detail?.token);if(e.detail?.token===active?.token)closeLocal();});
    let polling=false;
    const pending=async()=>{
      if(polling)return;polling=true;
      try{
        const r=await api.fetchApi("/dogma/local126/pending");if(!r.ok)return;
        const data=await r.json();
        if(active&&!data.items?.some(p=>p.token===active.token))closeLocal();
        const visible=data.items?.filter(p=>!submitted.has(p.token)&&p.phase!=="render")||[];
        const p=visible.find(p=>p.token===active?.token)||visible[0];if(p)showLocal(p);
      }catch(_){}finally{polling=false;}
    };
    api.addEventListener("reconnected",pending);pending();setInterval(pending,4000);
  }
});
