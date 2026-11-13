const paths={play:'M8 5l11 7-11 7z',pause:'M8 5v14M16 5v14',upload:'M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6',download:'M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4',folder:'M3 7V5h7l2 2h9v13H3z',plus:'M12 5v14M5 12h14',trash:'M3 6h18M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7M14 10v7',stop:'M6 6h12v12H6z',check:'M4 12l5 5L20 6',compare:'M3 4h18v16H3zM12 4v16',settings:'M4 7h16M4 17h16M9 4v6M15 14v6',refresh:'M20 7v5h-5M4 17v-5h5M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1',back:'M20 12H4m7-7-7 7 7 7',next:'M8 5l10 7-10 7M20 5v14',previous:'M16 5 6 12l10 7M4 5v14',film:'M3 4h18v16H3zM7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4',save:'M5 3h12l4 4v14H3V3zM7 3v6h10V3M7 21v-8h10v8',zoom:'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14M15 15l6 6M7 10h6',layers:'m12 3 10 6-10 6L2 9zM2 13l10 6 10-6M2 17l10 6 10-6'};
export function inferIcon(text){
 const s=text.toLowerCase();
 if(/ripristina|ricarica|riprova|nuovi seed/.test(s))return 'refresh';
 if(/02 provini|02 scegli/.test(s))return 'layers';if(/video edit/.test(s))return 'settings';
 if(/pausa/.test(s))return 'pause';if(/riproduci/.test(s))return 'play';if(/interrompi|annulla/.test(s))return 'stop';
 if(/rimuovi|elimina|libera/.test(s))return 'trash';if(/scarica/.test(s))return 'download';if(/carica|cambia file|cambia video/.test(s))return 'upload';
 if(/cartella/.test(s))return 'folder';if(/salva|applica/.test(s))return 'save';if(/scegli|usa|conferma/.test(s))return 'check';
 if(/confront|affiancati/.test(s))return 'compare';if(/zoom/.test(s))return 'zoom';if(/−1 fotogramma/.test(s))return 'previous';if(/\+1 fotogramma/.test(s))return 'next';
 if(/lora/.test(s))return 'layers';if(/maschera|impostazioni/.test(s))return 'settings';
 if(/torna|vai all/.test(s))return 'back';if(/ripristina|ricarica|riprova|nuovi seed/.test(s))return 'refresh';
 if(/^\+|aggiungi|nuova sessione/.test(s))return 'plus';if(/genera|provini|video|final|prepara|svilupp/.test(s))return 'film';return null;
}
export function setAction(button,text,icon=inferIcon(text)){
 const label=document.createElement('span');label.textContent=text;button.replaceChildren();button.classList.add('dg-action');
 if(icon&&paths[icon]){const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.classList.add('dg-icon');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.8');svg.setAttribute('stroke-linecap','round');svg.setAttribute('stroke-linejoin','round');svg.setAttribute('aria-hidden','true');const p=document.createElementNS(svg.namespaceURI,'path');p.setAttribute('d',paths[icon]);svg.append(p);button.append(svg);}
 button.append(label);return button;
}
export function actionButton(text,fn,cls=''){const b=document.createElement('button');b.type='button';b.className=cls;b.onclick=fn;return setAction(b,text);}
export function loraLabel(item){const stack=(item.loras||item.config?.common_loras||[]).filter(l=>l.name&&l.enabled!==false&&Number(l.strength??1)!==0),last=stack.at(-1);return last?last.name.replaceAll('\\','/').split('/').pop().replace(/\.safetensors$/i,'')+' · '+Number(last.strength??1).toLocaleString('it-IT'):'Senza LoRA';}
export function decorateActions(root){for(const b of root.querySelectorAll('button,a[download],summary'))if(!b.classList.contains('dg-edit-handle')&&!b.querySelector('.dg-icon')){const text=b.textContent,icon=inferIcon(text);if(icon)setAction(b,text,icon);}}
