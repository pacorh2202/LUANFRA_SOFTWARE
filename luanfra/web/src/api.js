const BASE = import.meta.env.VITE_API ?? "/api";

let claveAcceso = "";
export function configurarAcceso(clave) { claveAcceso = clave; }
export async function comprobarAcceso() { return pedir("/sesion"); }

async function pedir(ruta, opciones = {}) {
  const r = await fetch(`${BASE}${ruta}`, {
    ...opciones,
    headers: { ...opciones.headers, Authorization: `Bearer ${claveAcceso}` },
  });
  if (!r.ok) {
    let detalle = `Error ${r.status}`;
    try { detalle = (await r.json()).detail ?? detalle; } catch { /* respuesta sin json */ }
    throw new Error(typeof detalle === "string" ? detalle : "Revisa los campos introducidos: " + detalle.map(x => `${x.loc?.slice(1).join(".")}: ${x.msg}`).join("; "));
  }
  return r.status === 204 ? null : r.json();
}

const json = (cuerpo) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(cuerpo),
});

export const api = {
  plazo: (p) => pedir("/calculo/plazo", json(p)),
  kpis:    ()      => pedir("/panel/kpis"),
  ofertas: (p = {}) => pedir(`/ofertas?${new URLSearchParams(
                          Object.entries(p).filter(([, v]) => v))}`),
  oferta:  (id)    => pedir(`/ofertas/${id}`),
  aprobar: (id)    => pedir(`/ofertas/${id}/aprobar`, { method: "POST" }),
  corregir:(id, c) => pedir(`/ofertas/${id}/corregir`, json(c)),
  descartar:(id)   => pedir(`/ofertas/${id}/descartar`, { method: "POST" }),
};

const nf = (opts) => new Intl.NumberFormat("es-ES", opts);

export const eur = (v) => v == null ? "—"
  : nf({ style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(v);

export const eurExacto = (v) => v == null ? "—"
  : nf({ style: "currency", currency: "EUR" }).format(v);

export const fecha = (v) => v == null ? "—"
  : new Date(v).toLocaleDateString("es-ES", { day: "2-digit", month: "short", year: "2-digit" });

export const fechaCorta = (v) => v == null ? "—"
  : new Date(v).toLocaleDateString("es-ES", { day: "2-digit", month: "short" });

export const pct = (v) => v == null ? "—" : `${Math.round(v * 100)}%`;

export const horas = (min) => min == null ? "—"
  : `${Math.floor(min / 60)} h ${String(min % 60).padStart(2, "0")} min`;

/** "hace 3 meses" — más legible que una fecha suelta en una lista de comparables. */
export function haceTiempo(v) {
  if (!v) return "—";
  const dias = Math.round((Date.now() - new Date(v)) / 86400000);
  if (dias < 45) return `hace ${dias} d`;
  const meses = Math.round(dias / 30);
  if (meses < 22) return `hace ${meses} meses`;
  return `hace ${Math.round(dias / 365)} años`;
}
