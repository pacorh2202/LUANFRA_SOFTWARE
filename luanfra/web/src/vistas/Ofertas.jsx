import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search, AlertCircle, ChevronRight } from "lucide-react";
import { Cabecera } from "../componentes/Marco";
import { Panel, ChipVia, Esqueleto, Vacio } from "../componentes/Base";
import { api, eurExacto, fechaCorta, pct } from "../api";

const FILTROS = [
  { id: null,           txt: "Todas" },
  { id: "A_repetida",   txt: "Ya la hicimos" },
  { id: "B_similar",    txt: "Parecidas" },
  { id: "C_nueva",      txt: "Necesitan persona" },
];

export default function Ofertas() {
  const [datos, setDatos] = useState(null);
  const [via, setVia] = useState(null);
  const [busqueda, setBusqueda] = useState("");
  const [error, setError] = useState(null);
  const ir = useNavigate();

  useEffect(() => {
    setDatos(null);
    api.ofertas({ estado: "borrador", via })
      .then(setDatos).catch((e) => setError(e.message));
  }, [via]);

  const visibles = useMemo(() => {
    if (!datos) return null;
    const q = busqueda.trim().toLowerCase();
    if (!q) return datos;
    return datos.filter((o) =>
      `${o.cliente} ${o.pieza_ref} ${o.pieza_desc}`.toLowerCase().includes(q));
  }, [datos, busqueda]);

  return (
    <>
      <Cabecera
        titulo="Ofertas"
        subtitulo="Propuestas pendientes de tu revisión"
        derecha={
          <div className="relative">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-tinta-tenue" />
            <input
              value={busqueda}
              onChange={(e) => setBusqueda(e.target.value)}
              placeholder="Cliente o referencia…"
              className="h-9 w-64 pl-9 pr-3 rounded-lg border border-borde bg-white text-sm
                         placeholder:text-tinta-tenue focus:outline-none focus:ring-2 focus:ring-tinta/10"
            />
          </div>
        }
      />

      <div className="px-6 flex gap-2">
        {FILTROS.map((f) => (
          <button key={f.txt} onClick={() => setVia(f.id)}
            className={`px-3 h-8 rounded-lg text-sm font-medium transition border
              ${via === f.id
                ? "bg-tinta text-white border-tinta"
                : "bg-white text-tinta-suave border-borde hover:bg-lienzo"}`}>
            {f.txt}
          </button>
        ))}
      </div>

      <div className="px-6 py-4">
        <Panel>
          {error && <Vacio titulo="No se pudo cargar" texto={error} />}
          {!error && !visibles && <Esqueleto filas={6} />}
          {!error && visibles?.length === 0 && (
            <Vacio titulo="Nada pendiente por aquí"
                   texto="Cuando entre una petición nueva aparecerá en esta lista." />
          )}
          {visibles?.length > 0 && (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-tinta-tenue border-b border-borde">
                  <th className="font-medium px-4 py-2.5">Cliente</th>
                  <th className="font-medium px-4 py-2.5">Pieza</th>
                  <th className="font-medium px-4 py-2.5">Vía</th>
                  <th className="font-medium px-4 py-2.5 text-right">Precio</th>
                  <th className="font-medium px-4 py-2.5 text-right">Confianza</th>
                  <th className="font-medium px-4 py-2.5 text-right">Entrega</th>
                  <th className="w-8" />
                </tr>
              </thead>
              <tbody>
                {visibles.map((o) => (
                  <tr key={o.id} onClick={() => ir(`/ofertas/${o.id}`)}
                      className="border-b border-borde last:border-0 cursor-pointer hover:bg-lienzo transition group">
                    <td className="px-4 py-3">
                      <div className="font-medium">{o.cliente ?? "—"}</div>
                      <div className="text-xs text-tinta-tenue">{Math.round(o.cantidad)} ud</div>
                    </td>
                    <td className="px-4 py-3">
                      <div>{o.pieza_ref ?? "—"}</div>
                      <div className="text-xs text-tinta-tenue truncate max-w-[15rem]">{o.pieza_desc}</div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5">
                        <ChipVia via={o.via} />
                        {o.bloqueantes > 0 && (
                          <span title={`${o.bloqueantes} problema(s) en el plano`}>
                            <AlertCircle size={14} className="text-marca" />
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right cifra font-medium">
                      {o.precio_propuesto
                        ? eurExacto(o.precio_propuesto)
                        : <span className="text-tinta-tenue font-normal">sin precio</span>}
                    </td>
                    <td className="px-4 py-3 text-right cifra text-tinta-tenue">{pct(o.confianza)}</td>
                    <td className="px-4 py-3 text-right cifra text-tinta-tenue">
                      {fechaCorta(o.fecha_entrega_comprometible)}
                    </td>
                    <td className="pr-3 text-tinta-tenue opacity-0 group-hover:opacity-100 transition">
                      <ChevronRight size={16} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
        {visibles?.length > 0 && (
          <p className="mt-3 text-xs text-tinta-tenue">
            {visibles.length} oferta{visibles.length === 1 ? "" : "s"} en borrador.
            Ninguna se ha enviado a nadie.
          </p>
        )}
      </div>
    </>
  );
}
