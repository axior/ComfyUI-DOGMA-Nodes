// Geometry follows the supplied DOGMA artwork. No font glyph substitutes.
export function icon(name){
 const ns='http://www.w3.org/2000/svg',s=document.createElementNS(ns,'svg');s.setAttribute('viewBox','0 0 24 24');s.setAttribute('aria-hidden','true');s.classList.add('dap-icon');
 const paths={
  image:[['rect',{x:3,y:3,width:18,height:18,rx:2}],['circle',{cx:8,cy:8,r:1.1,fill:'currentColor'}],['path',{d:'M3 17l6-6 4 3 8-8'}]],
  video:[['rect',{x:3,y:3,width:18,height:18,rx:1}],['path',{d:'M3 7h18M3 17h18M7 3v4m5-4v4m5-4v4M7 17v4m5-4v4m5-4v4'}]],
  chevron:[['path',{d:'m7 10 5 5 5-5'}]],
  lines:[['path',{d:'M8 9h8M8 12h8M8 15h8'}]],
  single:[['rect',{x:3,y:4,width:18,height:16,rx:.6}]],
  grid:[['path',{d:'M2 4h5v6H2zM10 4h5v6h-5zM18 4h5v6h-5zM2 14h5v6H2zM10 14h5v6h-5zM18 14h5v6h-5z'}]],
  compare:[['rect',{x:2,y:4,width:20,height:16,rx:1}],['path',{d:'M12 4v16M4 17l3-10 3 10M5 13h4M15 7h2.5a2.5 2.5 0 0 1 0 5H15m0-5v10h3a2.5 2.5 0 0 0 0-5h-3'}]],
  play:[['path',{d:'M7 3l15 9L7 21z',fill:'currentColor',stroke:'none'}]],
  plus:[['path',{d:'M12 4v16M4 12h16'}]],
  close:[['path',{d:'m6 6 12 12M18 6 6 18'}]],
  folder:[['path',{d:'M2 6h8l2 3h10l-2 11H3zM2 6V4h8l2 2h8v3'}]],
  download:[['path',{d:'M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4'}]],
  edit:[['path',{d:'m4 16 12-12 4 4L8 20H4zm10-10 4 4M4 20h16'}]],
  zoomIn:[['circle',{cx:10,cy:10,r:7}],['path',{d:'m15 15 7 7M6 10h8M10 6v8'}]],
  zoomOut:[['circle',{cx:10,cy:10,r:7}],['path',{d:'m15 15 7 7M6 10h8'}]],
  fit:[['path',{d:'M3 9V3h6m6 0h6v6M3 15v6h6m6 0h6v-6'}]],
  refresh:[['path',{d:'M20 8a9 9 0 1 0 0 9M20 3v6h-6'}]],
  filter:[['path',{d:'M3 5h18l-7 8v7l-4-2v-5z'}]],
  arrow:[['path',{d:'m14 5-7 7 7 7'}]],
 };
 for(const [tag,attributes] of paths[name]||paths.plus){const p=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attributes))p.setAttribute(k,String(v));s.append(p);}
 return s;
}
