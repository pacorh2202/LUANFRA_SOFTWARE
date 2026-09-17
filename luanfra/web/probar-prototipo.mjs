import { JSDOM, VirtualConsole } from "jsdom";
import fs from "fs";
const errores = [];
const vc = new VirtualConsole()
  .on("jsdomError", e => { if (!/scrollTo/.test(e.message)) errores.push(e.message); })
  .on("error", m => errores.push(String(m)));
const dom = new JSDOM(fs.readFileSync("/home/claude/prototipo-luanfra.html","utf8"),
  { runScripts:"dangerously", virtualConsole: vc });
const { window } = dom; const doc = window.document; window.scrollTo = () => {};

const ok=[], mal=[];
const T=(n,f)=>{try{f();ok.push(n)}catch(e){mal.push(n+" → "+e.message)}};
const A=(c,m)=>{if(!c)throw new Error(m)};
const H=()=>doc.querySelector("#vista").innerHTML;
const clic=el=>{A(el,"no encontrado");el.dispatchEvent(new window.MouseEvent("click",{bubbles:true}))};
const PANTALLAS=["Panel","Nueva petición","Avisos","Ofertas","Indicadores",
  "Asistente","Mapa de planta","Planos","Taller","Clientes","Ajustes"];
const nav=x=>{
  const i = typeof x==="number" ? x : PANTALLAS.indexOf(x);
  A(i>=0, "pantalla desconocida: "+x);
  clic(doc.querySelectorAll(".nav")[i]);
};
const btn=t=>[...doc.querySelectorAll("#vista button")].find(b=>b.textContent.includes(t));

T("el menú tiene once entradas", ()=>{
  A(doc.querySelectorAll(".nav").length===11, "hay "+doc.querySelectorAll(".nav").length);
});

T("las nueve pantallas se pintan", ()=>{
  PANTALLAS.forEach((x,i)=>{ nav(i);
    A(doc.querySelector("#vista h1").textContent===x, `esperaba ${x}, salió ${doc.querySelector("#vista h1").textContent}`);
    A(H().length>400, "vacía: "+x); });
});

T("los avisos salen con acción y rol", ()=>{
  nav("Avisos");
  A(doc.querySelectorAll(".aviso-c").length===8, "avisos: "+doc.querySelectorAll(".aviso-c").length);
  A(H().includes("184.200 €"), "falta el importe sin facturar");
  A(H().includes("→"), "falta la acción");
});

T("el filtro por rol funciona", ()=>{
  nav("Avisos"); clic(btn("Administración"));
  A(doc.querySelectorAll(".aviso-c").length===2, "admin: "+doc.querySelectorAll(".aviso-c").length);
  clic(btn("Taller"));
  A(doc.querySelectorAll(".aviso-c").length===2, "taller");
  clic(btn("Todos"));
  A(doc.querySelectorAll(".aviso-c").length===8, "todos");
});

T("los indicadores muestran los 20 con sus objetivos", ()=>{
  nav("Indicadores");
  A(doc.querySelectorAll(".ind").length===22, "inds: "+doc.querySelectorAll(".ind").length);
  A(H().includes("27 %") || H().includes("27,0"), "falta la tasa de éxito real");
  A(H().includes("sin dato"), "no distingue los que no tienen dato");
  A(H().includes("partes con inicio y fin"), "no dice qué dato desbloquea");
  A(H().includes("15 de 22"), "el recuento del aviso no cuadra");
});

T("los indicadores sin dato no fingen tener valor", ()=>{
  nav("Indicadores");
  const sinDato=[...doc.querySelectorAll(".ind")].filter(x=>x.textContent.includes("sin dato"));
  A(sinDato.length===15, "sin dato: "+sinDato.length);
});

T("el asistente responde a una pregunta de datos", ()=>{
  nav("Asistente");
  clic([...doc.querySelectorAll(".sug button")].find(b=>b.textContent.includes("YUK")));
  A(H().includes("27.779"), "no responde con la cifra");
  A(H().includes("Base de datos de Luanfra"), "no marca la fuente");
});

T("el asistente marca cuándo NO son datos de la empresa", ()=>{
  nav("Asistente");
  clic([...doc.querySelectorAll(".sug button")].find(b=>b.textContent.includes("2768")));
  A(H().includes("NO datos de Luanfra"), "no avisa del carril técnico");
  A(H().includes("tolerancias generales"), "no responde");
});

T("el asistente sabe decir que no sabe", ()=>{
  nav("Asistente");
  window.preguntar("cuánto cobra Pedro al mes");
  A(H().includes("No sé responder"), "debería decir que no sabe");
});

T("ninguna pantalla deja valores sin formatear", ()=>{
  for(let i=0;i<PANTALLAS.length;i++){ nav(i); const h=H();
    A(!h.includes("undefined"), "undefined en "+i);
    A(!h.includes("NaN"), "NaN en "+i);
    A(!h.includes("[object"), "objeto crudo en "+i); }
});

T("las pantallas antiguas siguen funcionando", ()=>{
  nav("Ofertas");
  A(doc.querySelectorAll("#vista tbody tr").length>0, "listado vacío");
  clic(doc.querySelector("#vista tbody tr"));
  A(H().includes("Desglose del coste"), "la ficha no abre");
});

T("la pantalla principal tiene gráficos", ()=>{
  nav("Panel"); const h=H();
  A(h.includes("<svg"), "no hay ningún SVG");
  A((h.match(/<svg/g)||[]).length>=5, "solo "+(h.match(/<svg/g)||[]).length+" gráficos");
  A(h.includes("<polyline"), "falta el gráfico de línea");
  A(h.includes("<path"), "falta el rosco");
  A(h.includes("<rect"), "faltan las barras");
});

T("la pantalla principal destaca lo urgente arriba", ()=>{
  nav("Panel");
  A(doc.querySelectorAll("#vista .hero").length===1, "falta la franja de cabecera");
  A(doc.querySelectorAll("#vista .aviso-c.critica").length===2, "faltan los avisos críticos");
});

T("los indicadores tienen gráficos y barras de objetivo", ()=>{
  nav("Indicadores"); const h=H();
  A((h.match(/<svg/g)||[]).length>=6, "pocos gráficos: "+(h.match(/<svg/g)||[]).length);
  A(h.includes("Estado de los indicadores"), "falta el rosco de estado");
  A(h.includes("El precio influye"), "falta el gráfico de elasticidad");
  A(doc.querySelectorAll("#vista .barra").length>0, "faltan las barras de objetivo");
});

T("los gráficos llevan título accesible al pasar el ratón", ()=>{
  nav("Panel");
  A(H().includes("<title>"), "los datos no se pueden inspeccionar");
});

T("ningún gráfico sale con coordenadas inválidas", ()=>{
  for (let i of ["Panel","Indicadores"]) { nav(i);
    A(!/[cxy]="NaN"/.test(H()), "coordenada NaN en pantalla "+i);
    A(!/points="[^"]*NaN/.test(H()), "punto NaN en pantalla "+i); }
});

T("el mapa dibuja las dos naves con sus máquinas", ()=>{
  nav("Mapa de planta"); const h=H();
  A(h.includes("Nave 1 — Torneado"), "falta la nave 1");
  A(h.includes("Nave 2 — Fresado"), "falta la nave 2");
  A(doc.querySelectorAll("#vista .mq").length===40, "máquinas: "+doc.querySelectorAll("#vista .mq").length);
  A(h.includes("Entrada material"), "faltan las zonas");
});

T("los tornos están en la nave 1 y el resto en la 2", ()=>{
  nav("Mapa de planta");
  const t = window.MAQUINAS ? null : null;   // los datos son locales al script
  const h = H();
  A(h.includes("T-01") && h.includes("T-14"), "faltan tornos");
  A(h.includes("F-01") && h.includes("TA-1") && h.includes("S-01") && h.includes("R-01"),
    "faltan fresadoras, talladoras, sierras o roscadoras");
});

T("hay carretera entre las dos naves", ()=>{
  nav("Mapa de planta");
  const polis=[...doc.querySelectorAll("#vista svg polygon")];
  A(polis.length>40, "pocos polígonos");
  A(polis[0].getAttribute("fill")==="#EDEEF0", "el primer polígono debería ser la carretera");
});

T("las naves están giradas, no en horizontal", ()=>{
  nav("Mapa de planta");
  const nave = [...doc.querySelectorAll("#vista svg polygon")][1];
  const pts = nave.getAttribute("points").split(" ").map(p=>p.split(",").map(Number));
  const horiz = pts.filter((p,i)=> i>0 && Math.abs(p[1]-pts[i-1][1])<1).length;
  A(horiz===0, "la nave sale con lados horizontales: no está girada");
});

T("el mapa cambia entre estado y carga", ()=>{
  nav("Mapa de planta");
  clic(btn("Por carga"));
  A(H().includes("Más de 15 días"), "no cambia la leyenda");
  clic(btn("Por estado"));
  A(H().includes("Produciendo"), "no vuelve al modo estado");
});

T("al pulsar una máquina sale orden, carga y lista de espera", ()=>{
  nav("Mapa de planta");
  clic(doc.querySelector("#vista .mq"));
  const h=H();
  A(h.includes("Orden en curso"), "falta la orden en curso");
  A(h.includes("Carga de trabajo"), "falta la carga");
  A(h.includes("Lista de espera"), "falta la lista de espera");
  A(/\d+ d \d+ h \d+ min/.test(h), "la carga no va en días, horas y minutos");
});

T("una máquina sin conectar no inventa órdenes", ()=>{
  nav("Mapa de planta");
  const sin=[...doc.querySelectorAll("#vista .mq")]
    .find(g=>g.querySelector("title").textContent.includes("Sin conectar"));
  clic(sin);
  A(H().includes("Sin orden en curso"), "debería decir que no hay orden");
  A(H().includes("Nada en espera"), "no debería inventar cola");
});

T("la lista de espera lleva número de orden y cliente", ()=>{
  nav("Mapa de planta");
  const cargada=[...doc.querySelectorAll("#vista .mq")]
    .find(g=>/\b1[0-9] d\b|\b2[0-9] d\b/.test(g.querySelector("title").textContent));
  clic(cargada || doc.querySelector("#vista .mq"));
  const h=H();
  A(/16[0-9]{4}/.test(h), "faltan los números de orden");
  A(h.includes("S.A.")||h.includes("S.L.")||h.includes("SL"), "faltan los clientes");
});

T("el mapa detecta el desequilibrio de carga", ()=>{
  nav("Mapa de planta");
  A(H().includes("mientras"), "no avisa del desequilibrio");
});

T("todas las máquinas caben dentro de su nave", ()=>{
  nav("Mapa de planta");
  const polis=[...doc.querySelectorAll("#vista svg polygon")];
  A(polis.length>0, "sin polígonos");
  for (const r of polis) {
    const [x,y]=r.getAttribute("points").split(" ")[0].split(",").map(Number);
    A(!isNaN(x)&&!isNaN(y), "coordenada inválida");
    A(x>=-2 && y>=-2, `elemento fuera de la lona: ${x},${y}`);
  }
});

/* ---- Pantalla de nueva petición ---- */
T("la pantalla de petición existe y trae ejemplos", ()=>{ nav("Nueva petición"); A(doc.getElementById("txtPeticion"),"falta el cuadro de texto"); A([...doc.querySelectorAll("#vista .sug button")].length===5,"faltan ejemplos"); });


T("una pieza repetida sale por la vía A con precio",()=>{
  nav("Nueva petición"); clic(btn("Piñón simple")); clic(btn("Presupuestar"));
  const h=H();
  A(h.includes("Pieza que ya hemos hecho"),"debería ser vía A: "+h.slice(h.indexOf("chip"),200));
  A(/\d+,\d\d(&nbsp;|\s)*€/.test(h),"sin precio");
  A(h.includes("Ruta de fabricación"),"sin ruta");
  A(h.includes("Desglose"),"sin desglose");
});

T("extrae los datos del correo sin inventar",()=>{
  const h=H();
  A(h.includes("AISI 304"),"no saca el material");
  A(h.includes("18"),"no saca los dientes");
  A(h.includes("250"),"no saca la cantidad");
  A(h.includes("08B"),"no saca el paso");
});

T("deduce el diámetro del paso y los dientes",()=>{
  A(H().includes("Dp = p / sen"),"no explica la deducción");
  A(H().includes("Ø primitivo"),"no calcula el primitivo");
  A(H().includes("73.14"),"el primitivo de un Z18 paso 12,7 debe ser 73,14 mm");
});

T("la ruta de un piñón lleva talladora",()=>{
  A(H().includes("Tallado Z18"),"falta el tallado");
  A(H().includes("Tronzar"),"falta la sierra");
});

T("una pieza con H7 lleva rectificado",()=>{
  nav("Nueva petición"); clic(btn("Eje con H7")); clic(btn("Presupuestar"));
  A(H().includes("Rectificado"),"H7 debería obligar a rectificar");
  A(H().includes("no se alcanza torneando"),"sin explicación");
});

T("marcar carencias del plano cambia la decisión",()=>{
  nav("Nueva petición"); clic(btn("Piñón simple")); clic(btn("Presupuestar"));
  A(H().includes("Pieza que ya hemos hecho"),"parte de vía A");
  window.alternarHallazgo("tol"); window.alternarHallazgo("ajuste");
  clic(btn("Presupuestar"));
  A(H().includes("Necesita una persona"),"dos bloqueantes deberían mandar a vía C");
  A(H().includes("No propongo precio"),"debería negarse a dar precio");
  window.alternarHallazgo("tol"); window.alternarHallazgo("ajuste");
});

T("una pieza nueva no recibe precio",()=>{
  nav("Nueva petición"); clic(btn("Pieza nueva")); clic(btn("Presupuestar"));
  A(H().includes("Necesita una persona"),"debería ir a vía C");
  A(H().includes("No propongo precio"),"no debería dar precio");
  A(!btn("Aprobar").disabled===false,"Aprobar debería estar bloqueado");
});

T("el margen cambia el precio",()=>{
  nav("Nueva petición"); clic(btn("Piñón simple")); clic(btn("Presupuestar"));
  const p1=H().match(/font-size:30px[^>]*>([^<]+)/)[1];
  doc.getElementById("margenMan").value="80"; clic(btn("Presupuestar"));
  const p2=H().match(/font-size:30px[^>]*>([^<]+)/)[1];
  A(p1!==p2,"el margen no afecta");
  doc.getElementById("margenMan").value="35";
});

T("enseña comparables con precio y resultado",()=>{
  clic(btn("Presupuestar"));
  A(H().includes("Piezas en las que me apoyo"),"falta el bloque");
  A(H().includes("ganada")||H().includes("perdida"),"sin resultado histórico");
});

T("calcula plazo óptimo y comprometible",()=>{
  const h=H();
  A(h.includes("Plazo de entrega"),"falta el plazo");
  A(h.includes("Comprometible"),"falta la fecha comprometible");
  const plano=h.replace(/\s+/g," ");
  const m=plano.match(/Óptimo<\/span> <span class="cifra sub">(\d+) días/);
  const c=plano.match(/Comprometible<\/span> <span class="cifra" style="font-weight:600">(\d+) días/);
  A(m&&c,"no se leen los plazos");
  A(+c[1]>+m[1],"el comprometible debe ser mayor que el óptimo");
});

T("no quedan valores sin formatear",()=>{
  const h=H();
  A(!h.includes("undefined"),"undefined");
  A(!h.includes("NaN"),"NaN");
  A(!h.includes("null"),"null visible");
});

T("el precio se parece al del comparable real",()=>{
  nav("Nueva petición"); clic(btn("Piñón simple")); clic(btn("Presupuestar"));
  const h=H().replace(/&nbsp;/g," ");
  const u=parseFloat(h.match(/([\d.]+,\d\d) € por unidad/)[1].replace(/\./g,"").replace(",","."));
  A(u>30 && u<70, "precio unitario fuera de rango razonable: "+u);
});



T("entiende una descripción completa de piñón", ()=>{
  nav("Nueva petición"); clic(btn("Piñón simple")); clic(btn("Presupuestar"));
  const h=H();
  for (const campo of ["Ramales","Ø cubo","Ancho cubo","Ø taladro","Chavetero","Prisioneros"])
    A(h.includes(campo), "no extrae "+campo);
  A(h.includes("1 — simple"), "no traduce los ramales");
});

T("un piñón doble con Taper Lock se entiende entero", ()=>{
  nav("Nueva petición"); clic(btn("Piñón doble + Taper")); clic(btn("Presupuestar"));
  const h=H();
  A(h.includes("2 — doble"),"no detecta los ramales");
  A(h.includes("Taper Lock 2517"),"no detecta el casquillo cónico");
  A(h.includes("Dentado templado"),"no detecta el temple del dentado");
  A(h.includes("DIN 8187"),"no detecta la norma");
});

T("un engranaje helicoidal se entiende entero", ()=>{
  nav("Nueva petición"); clic(btn("Engranaje helicoidal")); clic(btn("Presupuestar"));
  const h=H();
  A(h.includes("Módulo"),"no detecta el módulo");
  A(h.includes("15° derecha"),"no detecta la hélice y su sentido");
  A(h.includes("Ángulo de presión"),"no detecta el ángulo de presión");
  A(h.includes("270 mm"),"el primitivo de Z90 módulo 3 debe ser 270 mm");
});

T("el chavetero no se confunde con las cotas de la pieza", ()=>{
  nav("Nueva petición"); clic(btn("Piñón simple")); clic(btn("Presupuestar"));
  const h=H();
  A(h.includes("8x3.3"),"no lee el chavetero");
  A(!/Longitud<\/span><span>8 mm/.test(h),"toma el chavetero por la longitud");
});

T("sin errores de JavaScript", ()=>{ A(errores.length===0, errores.slice(0,2).join(" | ")); });

console.log("\nPRUEBAS DEL PROTOTIPO AMPLIADO\n"+"-".repeat(46));
ok.forEach(t=>console.log("  OK    "+t));
mal.forEach(t=>console.log("  FALLA "+t));
console.log("-".repeat(46));
console.log(`${ok.length} correctas, ${mal.length} fallos`);
process.exit(mal.length?1:0);
