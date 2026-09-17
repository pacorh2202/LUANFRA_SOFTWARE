import { JSDOM, VirtualConsole } from "jsdom";
import fs from "fs";
const errs=[];
const vc=new VirtualConsole().on("jsdomError",e=>{if(!/scrollTo/.test(e.message))errs.push(e.message)})
  .on("error",m=>errs.push(String(m)));
const dom=new JSDOM(fs.readFileSync(new URL("../prototipo-luanfra.html", import.meta.url),"utf8"),
  {runScripts:"dangerously",virtualConsole:vc,url:"http://localhost/"});
const {window}=dom, doc=window.document; window.scrollTo=()=>{};
// jsdom no trae estas API del navegador: se aportan para poder probar
// ReadableStream y DecompressionStream tienen que venir de la MISMA
// implementación, o el pipeThrough falla en silencio.
const web = await import("node:stream/web");
window.ReadableStream = web.ReadableStream;
window.DecompressionStream = web.DecompressionStream;
window.TextDecoder = globalThis.TextDecoder;

const ok=[],mal=[];
const T=async(n,f)=>{try{await f();ok.push(n)}catch(e){mal.push(n+" → "+e.message)}};
const A=(c,m)=>{if(!c)throw new Error(m)};
const H=()=>doc.querySelector("#vista").innerHTML;
window.irA("peticion");

const ficheroFalso = (ruta, nombre) => {
  const buf = fs.readFileSync(ruta);
  return {name:nombre, size:buf.length,
          arrayBuffer: async () => buf.buffer.slice(buf.byteOffset, buf.byteOffset+buf.byteLength),
          text: async () => buf.toString("latin1")};
};

await T("lee un PDF comprimido y saca su texto", async ()=>{
  const r = await window.extraerTextoPDF(
    await ficheroFalso("../plantillas/planos-prueba/plano-completo.pdf","x.pdf").arrayBuffer());
  A(r.comprimidos>=1, "no detecta el flujo comprimido");
  A(r.texto.includes("ISO 2768"), "no extrae el texto: "+r.texto.slice(0,80));
  A(r.texto.includes("F-114"), "no saca el material");
});

await T("un plano completo pasa las ocho comprobaciones", async ()=>{
  const r = await window.extraerTextoPDF(
    await ficheroFalso("../plantillas/planos-prueba/plano-completo.pdf","x.pdf").arrayBuffer());
  const rev = window.revisarTextoPlano(r.texto);
  A(rev.legible, "no legible");
  A(rev.faltan.length===0, "faltan: "+rev.faltan.join(","));
});

await T("un plano incompleto señala lo que falta", async ()=>{
  const r = await window.extraerTextoPDF(
    await ficheroFalso("../plantillas/planos-prueba/plano-incompleto.pdf","x.pdf").arrayBuffer());
  const rev = window.revisarTextoPlano(r.texto);
  A(rev.faltan.includes("tol"), "no detecta la falta de tolerancia general");
  A(rev.faltan.includes("mat"), "no detecta la falta de material");
  A(rev.faltan.includes("rug"), "no detecta la falta de rugosidad");
});

await T("saca datos aprovechables del plano", async ()=>{
  const r = await window.extraerTextoPDF(
    await ficheroFalso("../plantillas/planos-prueba/plano-completo.pdf","x.pdf").arrayBuffer());
  const d = window.datosDePlano(r.texto);
  A(d.material==="F-114", "material: "+d.material);
  A(d.tolerancia==="H7", "tolerancia: "+d.tolerancia);
});

await T("detecta un plano escaneado y no inventa", async ()=>{
  const r = await window.extraerTextoPDF(
    await ficheroFalso("../plantillas/planos-prueba/plano-escaneado.pdf","x.pdf").arrayBuffer());
  A(!window.revisarTextoPlano(r.texto).legible, "debería marcarlo como ilegible");
});

await T("procesar un PDF marca solo las carencias", async ()=>{
  window.ficheros.length=0; window.peticion.hallazgos.length=0;
  await window.procesarFichero(ficheroFalso("../plantillas/planos-prueba/plano-incompleto.pdf","pinon.pdf"));
  A(window.ficheros.length===1 && window.ficheros[0].estado==="ok", "no procesa");
  A(window.peticion.hallazgos.includes("tol"), "no marca la tolerancia que falta");
  A(H().includes("pinon.pdf"), "no aparece en la lista");
});

await T("un plano completo no marca nada", async ()=>{
  window.ficheros.length=0; window.peticion.hallazgos.length=0;
  await window.procesarFichero(ficheroFalso("../plantillas/planos-prueba/plano-completo.pdf","eje.pdf"));
  A(window.peticion.hallazgos.length===0, "marca: "+window.peticion.hallazgos.join(","));
  A(window.ficheros[0].sugerido.includes("F-114"), "no propone los datos del plano");
});

await T("lee un STEP y saca protocolo y envolvente", async ()=>{
  window.ficheros.length=0;
  await window.procesarFichero(ficheroFalso(
    "../api/tests/datos/eje_ap242.step","eje.step"));
  const s = window.ficheros[0].step;
  A(s.protocolo==="AP242", "protocolo: "+s.protocolo);
  A(s.pmi.length>0, "no detecta tolerancias");
  A(s.envolvente && s.envolvente[2]>250, "envolvente: "+s.envolvente);
});

await T("un STEP de conjunto avisa de que son varias piezas", async ()=>{
  window.ficheros.length=0;
  await window.procesarFichero(ficheroFalso(
    "../api/tests/datos/conjunto_ap214.step","conjunto.step"));
  const s = window.ficheros[0].step;
  A(s.ensamblaje, "no detecta el ensamblaje");
  A(s.avisos.some(a=>a.includes("un fichero por pieza")), "no lo avisa");
  A(s.unidad==="pulgadas", "no detecta las pulgadas");
});

await T("un formato no soportado se rechaza sin romperse", async ()=>{
  window.ficheros.length=0;
  await window.procesarFichero({name:"dibujo.dwg", size:100,
    arrayBuffer:async()=>new ArrayBuffer(8), text:async()=>""});
  A(window.ficheros[0].estado==="no_soportado", "debería rechazarlo");
  A(H().includes("no soportado"), "no lo dice");
});

await T("sin errores de JavaScript", async ()=>{A(errs.length===0,errs.slice(0,2).join(" | "))});

console.log("\nPRUEBAS DE LECTURA DE FICHEROS\n"+"-".repeat(46));
ok.forEach(t=>console.log("  OK    "+t));
mal.forEach(t=>console.log("  FALLA "+t));
console.log(`${ok.length} correctas, ${mal.length} fallos`);
process.exit(mal.length?1:0);
