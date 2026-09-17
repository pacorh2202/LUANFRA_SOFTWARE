import { AlertCircle, AlertTriangle, Info } from "lucide-react";

/* ---------- Indicadores ---------- */

export function Kpi({ etiqueta, valor, pie, acento = false, cargando = false }) {
  return (
    <div className="card p-4">
      <div className="etiqueta">{etiqueta}</div>
      {cargando ? (
        <div className="mt-2 h-7 w-20 rounded bg-borde/60 animate-pulse" />
      ) : (
        <div className={`mt-1.5 text-2xl font-semibold cifra ${acento ? "text-marca" : "text-tinta"}`}>
          {valor}
        </div>
      )}
      {pie && <div className="mt-0.5 text-xs text-tinta-tenue">{pie}</div>}
    </div>
  );
}

const TONOS = {
  verde: "bg-exito-claro text-exito",
  ambar: "bg-aviso-claro text-aviso",
  rojo:  "bg-marca-claro text-marca",
  gris:  "bg-lienzo text-tinta-tenue border border-borde",
};

export function Chip({ tono = "gris", punto = true, children }) {
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium whitespace-nowrap ${TONOS[tono]}`}>
      {punto && <span className="w-1.5 h-1.5 rounded-full bg-current opacity-70" />}
      {children}
    </span>
  );
}

/** Las tres vías, con el MISMO código de color en toda la aplicación. */
export const VIAS = {
  A_repetida: { texto: "Ya la hicimos",    tono: "verde" },
  B_similar:  { texto: "Parecida",         tono: "ambar" },
  C_nueva:    { texto: "Necesita persona", tono: "rojo"  },
};

export function ChipVia({ via }) {
  const v = VIAS[via] ?? { texto: via, tono: "gris" };
  return <Chip tono={v.tono}>{v.texto}</Chip>;
}

export function ChipEstado({ estado }) {
  const m = { borrador: "gris", revisada: "verde", enviada: "verde", descartada: "rojo" };
  return <Chip tono={m[estado] ?? "gris"} punto={false}>{estado}</Chip>;
}

export function Barra({ pct, tono }) {
  const color = tono ?? (pct > 80 ? "bg-exito" : pct > 55 ? "bg-aviso" : "bg-marca");
  return (
    <div className="h-1.5 w-full bg-lienzo rounded-full overflow-hidden">
      <div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${Math.min(100, pct)}%` }} />
    </div>
  );
}

/* ---------- Contenedores ---------- */

export function Panel({ titulo, accion, children, sinBorde = false, className = "" }) {
  return (
    <section className={`card overflow-hidden ${className}`}>
      {(titulo || accion) && (
        <header className={`flex items-center justify-between px-4 h-12 ${sinBorde ? "" : "border-b border-borde"}`}>
          <h2 className="text-sm font-semibold">{titulo}</h2>
          {accion}
        </header>
      )}
      {children}
    </section>
  );
}

export function Fila({ etiqueta, valor, fuerte = false, tenue = false }) {
  return (
    <div className="flex items-baseline justify-between gap-4 text-sm">
      <span className="text-tinta-tenue">{etiqueta}</span>
      <span className={`cifra ${fuerte ? "font-semibold" : ""} ${tenue ? "text-tinta-tenue" : ""}`}>
        {valor}
      </span>
    </div>
  );
}

/* ---------- Avisos ---------- */

const AVISOS = {
  bloqueante: { icono: AlertCircle,   clase: "bg-marca-claro text-marca" },
  importante: { icono: AlertTriangle, clase: "bg-aviso-claro text-aviso" },
  menor:      { icono: Info,          clase: "bg-lienzo text-tinta-tenue" },
};

export function Aviso({ gravedad = "menor", children }) {
  const { icono: I, clase } = AVISOS[gravedad] ?? AVISOS.menor;
  return (
    <div className={`flex gap-2.5 p-3 rounded-lg ${clase}`}>
      <I size={15} className="shrink-0 mt-0.5" strokeWidth={2} />
      <p className="text-xs leading-relaxed">{children}</p>
    </div>
  );
}

/* ---------- Estados de carga y vacío ---------- */

export function Esqueleto({ filas = 5 }) {
  return (
    <div className="p-4 space-y-3">
      {Array.from({ length: filas }).map((_, i) => (
        <div key={i} className="h-9 rounded bg-borde/50 animate-pulse" />
      ))}
    </div>
  );
}

export function Vacio({ titulo, texto }) {
  return (
    <div className="py-14 text-center">
      <p className="text-sm font-medium">{titulo}</p>
      {texto && <p className="text-xs text-tinta-tenue mt-1">{texto}</p>}
    </div>
  );
}
