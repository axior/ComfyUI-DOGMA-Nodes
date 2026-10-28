import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const GENERATE="GENERA PROVINI", FINISH="FINALIZZA SELEZIONATO";
const SEEDS="SEED DIVERSI / stesso prompt", PROMPTS="PROMPT DIVERSI / stesso seed";
const widget=(n,k)=>n?.widgets?.find(w=>w.name===k);
function set(n,k,v){
    const w=widget(n,k);if(!w)throw new Error(`Controllo mancante: ${k}. Importa il workflow DOGMA completo.`);
    w.value=v;w.callback?.(v);n.setDirtyCanvas?.(true,true);app.graph?.change?.();
}
function el(tag,text="",cls=""){const e=document.createElement(tag);e.textContent=text;e.className=cls;return e;}
function btn(text,fn,cls=""){const b=el("button",text,cls);b.type="button";b.onclick=fn;return b;}
const viewURL=(e,type="output")=>api.apiURL("/view?"+new URLSearchParams({filename:e.filename,subfolder:e.subfolder||"",type:e.type||type}));
function movie(src){const v=el("video");v.controls=true;v.loop=true;v.muted=true;v.playsInline=true;v.preload="metadata";if(src)v.src=src;return v;}

app.registerExtension({name:"DOGMA.H3.Director",async beforeRegisterNodeDef(nodeType,nodeData){
    if(nodeData.name!=="DOGMAH3Auditions")return;
    const created=nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated=function(){
        created?.apply(this,arguments);const node=this;node.properties??={};
        if(!widget(node,"session_id")?.value)set(node,"session_id",crypto.randomUUID());
        for(const name of ["session_id","nuovo_giro","azione","modalita","numero_provini","provino_scelto"]){
            const w=widget(node,name);if(w){w.type="converted-widget";w.computeSize=()=>[0,-4];}
        }
        const root=el("div","","dogma-director"),css=el("style");
        root.style.cssText="width:100%;height:1030px;box-sizing:border-box;overflow:auto;background:#101112;color:#eee;border:1px solid #7f3b22;border-radius:10px;font:14px/1.5 Arial,sans-serif";
        css.textContent=`
          .dogma-director *{box-sizing:border-box}.dogma-director h2,.dogma-director h3{margin:0 0 10px}
          .dogma-director button{cursor:pointer;padding:10px 14px;border:1px solid #555;border-radius:6px;background:#26282a;color:#eee;font:600 13px Arial}
          .dogma-director button:hover{border-color:#ff631e}.dogma-director button:disabled{opacity:.4;cursor:default}
          .dogma-director button.hot,.dogma-director button.active{background:#df5317;border-color:#ff7a3e;color:#fff}
          .dogma-director textarea,.dogma-director input,.dogma-director select{width:100%;padding:10px;border:1px solid #515357;background:#191b1d;color:#eee;border-radius:6px;font:14px/1.5 Arial}
          .dogma-director textarea{resize:vertical;min-height:72px}.dogma-director label{display:block;color:#b9bcc0;font-size:12px;letter-spacing:.5px;margin:7px 0}
          .dogma-director .head{padding:20px 24px;border-bottom:1px solid #555;display:flex;justify-content:space-between;align-items:center}
          .dogma-director .brand{font-size:34px;font-weight:900;letter-spacing:-2px}.dogma-director .orange{color:#ff7637;letter-spacing:3px;font-size:12px}
          .dogma-director .tabs,.dogma-director .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.dogma-director .tabs{padding:14px 24px;border-bottom:1px solid #333}
          .dogma-director .body{padding:20px 24px}.dogma-director .cols{display:grid;grid-template-columns:minmax(240px,1fr) minmax(350px,1.55fr);gap:20px}
          .dogma-director .box{padding:16px;background:#191b1d;border:1px solid #36383b;border-radius:8px;margin-bottom:15px}
          .dogma-director .small{font-size:12px;color:#a5a9ae}.dogma-director .status{padding:12px 24px;color:#ffae87;background:#211a17;min-height:48px}
          .dogma-director img,.dogma-director video{display:block;width:100%;object-fit:contain;background:#090a0b;border-radius:5px}
          .dogma-director [hidden]{display:none!important}.dogma-director .live{height:235px}
          .dogma-director .grid{display:grid;grid-template-columns:repeat(3,minmax(200px,1fr));gap:14px}
          .dogma-director .card{padding:10px;border:2px solid #36383b;border-radius:8px;background:#191b1d;min-width:0}.dogma-director .card video{height:170px}
          .dogma-director .card p{font-size:12px;max-height:70px;overflow:auto}.dogma-director .compare{display:grid;grid-template-columns:1fr 1fr;gap:12px}
          .dogma-director .compare video{height:260px}.dogma-director .variant{display:flex;gap:8px;margin-top:8px;align-items:start}.dogma-director .variant textarea{min-height:66px}
          .dogma-director .variant span{padding-top:10px;color:#ff824d}.dogma-director .footer{padding:0 24px 16px;color:#92979c;font-size:12px}
        `;
        const head=el("div","","head");head.append(el("div","DOGMA","brand"),el("div","ORIGINALS / H3 DIRECTOR","orange"));
        const tabs=el("div","","tabs"),status=el("div","Carica un'immagine, prepara il prompt e genera i provini.","status"),body=el("div","","body");
        const panels=[el("div"),el("div"),el("div")];body.append(...panels);
        const tabButtons=["01  PREPARA","02  PROVINI / A·B","03  FINALIZZA"].map((s,i)=>btn(s,()=>show(i)));tabs.append(...tabButtons);
        root.append(css,head,tabs,status,body,el("div","Controlli avanzati nei gruppi sottostanti · preview KJ agli step disponibili · una sola esecuzione alla volta","footer"));
        function show(i){panels.forEach((p,k)=>p.hidden=k!==i);tabButtons.forEach((b,k)=>b.className=k===i?"active":"");}
        let busy=false,uploading=false,manifest,selected,variants=[],changed=false,liveURL;
        function target(role){const g=node.graph||app.graph,id=node.properties.dogma_bindings?.[role];return g?.getNodeById?.(id)||g?._nodes?.find(n=>n.properties?.dogma_role===role);}
        function read(role){return widget(target(role),role==="source"?"image":"value")?.value;}
        function write(role,value){set(target(role),role==="source"?"image":"value",value);changed=true;if(manifest)status.textContent="Preparazione modificata: genera un nuovo giro prima di finalizzare.";}
        const edits=[];
        function field(label,input,parent){parent.append(el("label",label),input);edits.push(input);return input;}
        const cols=el("div","","cols"),left=el("div"),right=el("div");cols.append(left,right);panels[0].append(cols);
        const imageBox=el("div","","box"),image=el("img"),fileInput=el("input");image.style.height="260px";image.alt="Immagine iniziale";
        fileInput.type="file";fileInput.accept="image/*";fileInput.hidden=true;
        const upload=btn("Carica / cambia immagine",()=>fileInput.click());edits.push(upload);
        imageBox.append(el("h3","Immagine iniziale"),image,upload,fileInput);left.append(imageBox);
        function sourcePreview(){
            const name=read("source");if(!name){image.removeAttribute("src");return;}
            const s=name.replace(/ \[(input|temp|output)\]$/,""),i=s.lastIndexOf("/");
            image.src=viewURL({filename:s.slice(i+1),subfolder:i<0?"":s.slice(0,i)},"input");
        }
        fileInput.onchange=async()=>{
            const file=fileInput.files?.[0];if(!file)return;uploading=true;updateBusy(true);status.textContent="Caricamento immagine…";
            try{
                const data=new FormData();data.append("image",file);data.append("type","input");data.append("overwrite","false");
                const r=await api.fetchApi("/upload/image",{method:"POST",body:data});if(!r.ok)throw new Error("Caricamento non riuscito.");
                const item=await r.json();write("source",[item.subfolder,item.name].filter(Boolean).join("/"));sourcePreview();status.textContent="Immagine caricata. Prepara il prompt.";
            }catch(e){status.textContent=e.message;}finally{uploading=false;updateBusy(false);}
        };
        const quality=el("div","","box"),preset=el("select");left.append(quality);
        [["672x384","Paesaggio · 672 × 384"],["384x672","Verticale · 384 × 672"],["512x512","Quadrato · 512 × 512"]].forEach(([v,t])=>{const o=el("option",t);o.value=v;preset.append(o);});
        field("FORMATO PROVINI · finale ×2",preset,quality);preset.onchange=()=>{const [w,h]=preset.value.split("x").map(Number);write("width",w);write("height",h);};
        const duration=el("input");duration.type="number";duration.min="1";duration.max="10";duration.step="0.5";
        field("DURATA RICHIESTA · secondi",duration,quality);
        duration.onchange=()=>{const v=Number(duration.value);if(v>=1&&v<=10)write("duration",v);else duration.value=read("duration");};
        quality.append(el("p","H3 allinea i fotogrammi: 5 s corrispondono a circa 5,17 s. Il tempo di calcolo dipende dalla GPU.","small"));
        const prompt=el("textarea");prompt.rows=5;field("PROMPT COMUNE · soggetto, azione, camera",prompt,right);prompt.oninput=()=>write("prompt",prompt.value);
        const modes=el("div","","row");modes.style.margin="15px 0";
        const seedMode=btn("Seed diversi",()=>mode(SEEDS)),promptMode=btn("Prompt diversi",()=>mode(PROMPTS));modes.append(seedMode,promptMode);right.append(modes);edits.push(seedMode,promptMode);
        const countBox=el("div","","box"),count=el("input");count.type="number";count.min="1";count.max="10";
        field("QUANTI PROVINI · 1–10",count,countBox);countBox.append(el("div","Stesso prompt, un seed diverso per ogni clip.","small"));right.append(countBox);
        count.onchange=()=>{const v=Math.max(1,Math.min(10,Math.round(Number(count.value)||1)));count.value=v;set(node,"numero_provini",v);changed=true;};
        const variantBox=el("div","","box"),variantList=el("div");variantBox.append(el("h3","Varianti di prompt"),el("div","Ogni scheda si aggiunge al prompt comune. Puoi lasciare il comune vuoto e scrivere prompt completi. Un unico seed condiviso; nessuna griglia.","small"),variantList);
        const addVariant=btn("+ Aggiungi variante",()=>{if(variants.length<10){variants.push("");drawVariants();saveVariants();}});edits.push(addVariant);variantBox.append(addVariant);right.append(variantBox);
        function saveVariants(){write("variants",variants.join("\n"));}
        function drawVariants(){variantList.replaceChildren();variants.forEach((text,i)=>{
            const row=el("div","","variant"),input=el("textarea");input.value=text;input.disabled=busy;
            input.oninput=()=>{variants[i]=input.value.replace(/\r?\n/g," ");saveVariants();};
            const remove=btn("×",()=>{variants.splice(i,1);drawVariants();saveVariants();});remove.disabled=busy;
            row.append(el("span",String(i+1).padStart(2,"0")),input,remove);variantList.append(row);
        });addVariant.disabled=busy||variants.length>=10;}
        function mode(v,store=true){if(store){set(node,"modalita",v);changed=true;}countBox.hidden=v!==SEEDS;variantBox.hidden=v!==PROMPTS;seedMode.className=v===SEEDS?"active":"";promptMode.className=v===PROMPTS?"active":"";}
        const generate=btn("▶ Genera provini",()=>queue(GENERATE),"hot"),stop=btn("■ Interrompi",async()=>{
            if(!busy)return;try{await api.fetchApi("/interrupt",{method:"POST"});status.textContent="Interruzione richiesta…";}catch(e){status.textContent=e.message;}
        });stop.disabled=true;tabs.append(generate,stop);
        const liveBox=el("div","","box"),liveLabel=el("div","Preview live · in attesa di campionamento","small"),liveImage=el("img","","live"),liveVideo=movie();
        liveImage.alt="Preview KJ";liveImage.hidden=true;liveVideo.className="live";liveVideo.hidden=true;liveVideo.autoplay=true;liveBox.append(liveLabel,liveImage,liveVideo);panels[1].append(liveBox);
        const compareBox=el("div","","box"),compare=el("div","","compare"),av=movie(),bv=movie(),al=el("div","A"),bl=el("div","B"),ac=el("div"),bc=el("div");compareBox.hidden=true;
        ac.append(al,av);bc.append(bl,bv);compare.append(ac,bc);
        compareBox.append(el("h3","Confronto A / B"),compare,btn("▶ Riproduci insieme",()=>{
            for(const v of grid.querySelectorAll("video"))v.pause();av.currentTime=0;bv.currentTime=0;av.play()?.catch(()=>{});bv.play()?.catch(()=>{});
        }),btn("Chiudi confronto",()=>{av.pause();bv.pause();compareBox.hidden=true;}));panels[1].append(compareBox);
        const grid=el("div","","grid"),empty=el("p","Qui compariranno i provini: guardali, confrontane due e scegli quello da continuare.","small");panels[1].append(grid,empty);
        const chosenTitle=el("h2","Scegli un provino"),chosenVideo=movie(),chosenPrompt=el("p","","small");chosenVideo.style.height="300px";
        const finalBox=el("div","","box"),finalControls=el("div","","row"),rife=el("input");rife.type="checkbox";rife.style.width="auto";
        const rifeLabel=el("label","Interpolazione finale a 48 fps");rifeLabel.prepend(rife);rife.onchange=()=>set(target("rife"),"value",rife.checked);
        const finalize=btn("▶ Finalizza questo",()=>queue(FINISH),"hot");finalize.disabled=true;finalControls.append(finalize,rifeLabel,btn("← Torna ai provini",()=>show(1)));
        finalBox.append(chosenTitle,chosenVideo,chosenPrompt,finalControls,el("p","Continua dai latenti scelti con upscale ×2 e raffinamento. Prompt e seed vengono ripresi automaticamente. Il secondo passaggio può variare dettagli e movimento.","small"));panels[2].append(finalBox);
        const result=movie(),resultLink=el("a","Apri video salvato");result.hidden=true;result.style.height="330px";result.muted=false;resultLink.hidden=true;resultLink.target="_blank";resultLink.style.color="#ff874c";
        panels[2].append(el("h3","Risultato finale"),result,resultLink);
        function updateBusy(v){busy=v;generate.disabled=v;stop.disabled=!v||uploading;finalize.disabled=v||!selected;rife.disabled=v;edits.forEach(e=>e.disabled=v);
            for(const e of variantList.querySelectorAll("textarea,button"))e.disabled=v;for(const e of grid.querySelectorAll("button"))e.disabled=v;addVariant.disabled=v||variants.length>=10;
        }
        async function queue(action){
            if(busy)return;
            updateBusy(true);
            try{
                for(const role of ["source","prompt","variants","width","height","duration","rife","final","live_scout","live_final"])if(!target(role))throw new Error(`Collegamento Director mancante: ${role}. Usa il workflow incluso.`);
                if(!read("source"))throw new Error("Carica prima l'immagine iniziale.");
                if(action===GENERATE&&widget(node,"modalita").value===SEEDS&&!String(read("prompt")||"").trim())throw new Error("Scrivi prima il prompt comune.");
                if(action===GENERATE&&widget(node,"modalita").value===PROMPTS&&!variants.some(x=>x.trim()))throw new Error("Aggiungi almeno una variante di prompt.");
                if(action===FINISH&&(!selected||changed))throw new Error("La preparazione è cambiata: genera nuovi provini prima di finalizzare.");
                const response=await api.fetchApi("/queue");if(!response.ok)throw new Error("Non riesco a leggere la coda ComfyUI.");const q=await response.json();
                if(q.queue_running?.length||q.queue_pending?.length)throw new Error("ComfyUI ha già un lavoro in coda. Attendi che termini.");
                set(node,"azione",action);if(action===GENERATE)set(node,"nuovo_giro",Number(widget(node,"nuovo_giro").value)+1);
                updateBusy(true);show(action===GENERATE?1:2);status.textContent=action===GENERATE?"Avvio provini · caricamento modelli e preparazione…":"Avvio finale · recupero del provino scelto…";
                const queued=await app.queuePrompt(0,1);if(queued===false)throw new Error("ComfyUI non ha accettato il workflow. Controlla l'errore dei nodi.");
            }catch(e){updateBusy(false);status.textContent=e.message;}
        }
        function select(entry){selected=entry;node.properties.dogma_selected=entry.index;set(node,"provino_scelto",entry.index);set(node,"azione",FINISH);
            for(const card of grid.children)card.style.borderColor=Number(card.dataset.index)===entry.index?"#ff631e":"#36383b";
            chosenTitle.textContent=`Provino ${String(entry.index).padStart(2,"0")} · pronto da continuare`;chosenVideo.src=viewURL(entry);chosenPrompt.textContent=entry.prompt;
            finalize.disabled=busy;status.textContent=`Provino ${entry.index} selezionato. Premi «Finalizza questo».`;show(2);
        }
        function draw(data,index=0){
            if(!data?.complete)return;manifest=data;node.properties.dogma_gallery=data;grid.replaceChildren();empty.hidden=true;selected=null;changed=false;compareBox.hidden=true;av.pause();bv.pause();
            for(const entry of data.candidates){const card=el("div","","card");card.dataset.index=String(entry.index);const v=movie(viewURL(entry));
                v.addEventListener("play",()=>{for(const other of grid.querySelectorAll("video"))if(other!==v)other.pause();});const actions=el("div","","row");
                actions.append(btn("Scegli",()=>select(entry),"hot"),btn("A",()=>{compareBox.hidden=false;av.src=viewURL(entry);al.textContent=`A · Provino ${entry.index}`;}),btn("B",()=>{compareBox.hidden=false;bv.src=viewURL(entry);bl.textContent=`B · Provino ${entry.index}`;}));
                card.append(el("h3",`PROVINO ${String(entry.index).padStart(2,"0")}`),v,el("div",`${entry.width} × ${entry.height} · ${(entry.frames/24).toFixed(2)} s`,"small"),el("p",entry.variant||"Prompt comune · seed diverso"),actions);card.title=entry.prompt;grid.append(card);
            }updateBusy(false);
            if(index){const entry=data.candidates.find(e=>e.index===index);if(entry)select(entry);}else{node.properties.dogma_selected=0;chosenTitle.textContent="Scegli un provino";chosenVideo.removeAttribute("src");finalize.disabled=true;show(1);status.textContent=`${data.candidates.length} provini pronti · ${Number(data.total_seconds).toFixed(1)} s totali. Confronta e scegli.`;}
        }
        function sync(){prompt.value=read("prompt")||"";count.value=widget(node,"numero_provini")?.value||10;duration.value=read("duration")||5;rife.checked=!!read("rife");
            const dimensions=`${read("width")}x${read("height")}`;if(!Array.from(preset.options).some(o=>o.value===dimensions)){const o=el("option",`Personalizzato · ${dimensions}`);o.value=dimensions;preset.append(o);}preset.value=dimensions;
            sourcePreview();variants=String(read("variants")||"").split("\n").filter(x=>x.trim());drawVariants();mode(widget(node,"modalita")?.value||SEEDS,false);
        }
        tabs.append(btn("↻ Sincronizza controlli",()=>{sync();status.textContent="Controlli aggiornati dai nodi del workflow.";}));
        tabs.append(btn("⛶ Schermo intero",async()=>{
            try{if(document.fullscreenElement===root)await document.exitFullscreen();else await root.requestFullscreen();}
            catch{status.textContent="Schermo intero non disponibile in questo browser. Il pannello resta utilizzabile nel nodo.";}
        }));
        const fullscreen=()=>{root.style.height=document.fullscreenElement===root?"100vh":"1030px";};
        document.addEventListener("fullscreenchange",fullscreen);
        const listeners=[];function listen(k,f){api.addEventListener(k,f);listeners.push([k,f]);}
        listen("dogma.h3.status",e=>{if(String(e.detail.node)===String(node.id))status.textContent=e.detail.message;});
        listen("kj_preview_override",e=>{
            const d=e.detail,scout=String(d.node_id)===String(target("live_scout")?.id),final=String(d.node_id)===String(target("live_final")?.id);if((!scout&&!final)||!d.image)return;
            liveLabel.textContent=`${scout?"PROVINI":"FINALE"} · step ${d.step} / ${d.total}`;const mime=d.mime||"image/jpeg";
            if(mime.startsWith("video/")){if(liveURL)URL.revokeObjectURL(liveURL);const bytes=Uint8Array.from(atob(d.image),c=>c.charCodeAt(0));liveURL=URL.createObjectURL(new Blob([bytes],{type:mime}));liveVideo.src=liveURL;liveVideo.hidden=false;liveImage.hidden=true;liveVideo.play()?.catch(()=>{});}
            else{liveImage.src=`data:${mime};base64,${d.image}`;liveImage.hidden=false;liveVideo.hidden=true;liveVideo.pause();}
            (final?panels[2]:panels[1]).prepend(liveBox);
        });
        function showResult(e){result.src=viewURL(e);result.hidden=false;resultLink.href=result.src;resultLink.hidden=false;}
        listen("executed",e=>{const d=e.detail;if(String(d.node)!==String(target("final")?.id))return;const item=d.output?.images?.[0];if(!item?.filename)return;
            node.properties.dogma_final=item;showResult(item);updateBusy(false);status.textContent="Finale pronto e salvato. Puoi continuare un altro provino dello stesso giro.";
        });
        listen("execution_error",e=>{if(busy){updateBusy(false);status.textContent=`Errore ComfyUI: ${e.detail.exception_message||"controlla il nodo segnalato"}`;}});
        listen("execution_interrupted",()=>{if(busy){updateBusy(false);status.textContent="Interrotto. Il precedente giro completo resta disponibile.";}});
        listen("executing",e=>{if(busy&&e.detail===null)updateBusy(false);});
        const executed=node.onExecuted;node.onExecuted=function(message){executed?.apply(this,arguments);if(message.dogma_gallery?.[0]){
            const finishing=widget(node,"azione")?.value===FINISH;draw(message.dogma_gallery[0],message.dogma_selected?.[0]||0);if(finishing)updateBusy(true);
        }};
        const configured=node.onConfigure;node.onConfigure=function(){configured?.apply(this,arguments);setTimeout(()=>{
            sync();if(node.properties.dogma_gallery)draw(node.properties.dogma_gallery,node.properties.dogma_selected||0);if(node.properties.dogma_final)showResult(node.properties.dogma_final);
        },0);};
        node.addDOMWidget("dogma_director","DOGMA_H3_DIRECTOR",root,{serialize:false,hideOnZoom:false,getValue:()=>"",setValue:()=>{},getMinHeight:()=>1030,getMaxHeight:()=>1030,getHeight:()=>1030});
        node.size[0]=Math.max(node.size[0],1240);show(0);
        const removed=node.onRemoved;node.onRemoved=function(){document.removeEventListener("fullscreenchange",fullscreen);listeners.forEach(([k,f])=>api.removeEventListener(k,f));if(liveURL)URL.revokeObjectURL(liveURL);for(const v of root.querySelectorAll("video")){v.pause();v.removeAttribute("src");v.load();}removed?.apply(this,arguments);};
    };
}});
