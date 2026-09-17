import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AlertCircle, ArrowRight } from "lucide-react";
import { Cabecera } from "../componentes/Marco";
import { Kpi, Panel, ChipVia, Esqueleto, Vacio } from "../componentes/Base";
import { api, eur, eurExacto, fechaCorta } from "../api";

export default function PanelPrincipal() {
  const [kpis, setKpis] = useState(null);
  const [ofertas, setOfertas] = useState(null);
  const [error, setError] = useState(null);
  const ir = useNavigate();

  useEffect(() => {
    Promise.all([api.kpis(), api.ofertas({ estado: "borrador", limite: 8 })])
      .then(([k, o]) => { setKpis(k); setOfertas(o); })
      .catch((e) => setError(e.message));
  }, []);

  const requieren = kpis?.requieren_persona ?? 0;

  return (
    <>
      <Cabecera
        titulo="Panel"
        subtitulo={kpis
          ? `${kpis.ofertas_por_revisar} ofertas esperan tu revisión`
          : "Cargando…"}
      />

      <div className="grid grid-cols-4 gap-4 px-6">
        <Kpi etiqueta="Peticiones sin procesar" valor={kpis?.peticiones_pendientes ?? "—"}
             cargando={!kpis && !error} />
        <Kpi etiqueta="Ofertas por revisar" valor={kpis?.ofertas_por_revisar ?? "—"}
             cargando={!kpis && !error} />
        <Kpi etiqueta="Importe en revisión" valor={eur(kpis?.importe_por_revisar)}
             cargando={!kpis && !error} />
        <Kpi etiqueta="Necesitan una persona" valor={requieren} acento={requieren > 0}
             pie={requieren > 0 ? "El sistema no propone precio" : "Ninguna atascada"}
             cargando={!kpis && !error} />
      </div>

      <div className="px-6 py-4">
        <Panel
          titulo="Lo más reciente"
          accion={
            <Link to="/ofertas" className="text-sm text-tinta-tenue hover:text-tinta flex items-center gap-1">
              Ver todas <ArrowRight size={14} />
            </Link>
          }>
          {error && <Vacio titulo="No se pudo cargar" texto={error} />}
          {!error && !ofertas && <Esqueleto filas={5} />}
          {ofertas?.length === 0 && <Vacio titulo="Nada pendiente" />}
          {ofertas?.length > 0 && (
            <table className="w-full text-sm">
              <tbody>
                {ofertas.map((o) => (
                  <tr key={o.id} onClick={() => ir(`/ofertas/${o.id}`)}
                      className="border-b border-borde last:border-0 cursor-pointer hover:bg-lienzo transition">
                    <td className="px-4 py-3">
                      <div className="font-medium">{o.cliente ?? "—"}</div>
                      <div className="text-xs text-tinta-tenue">
                        {o.pieza_ref} · {Math.round(o.cantidad)} ud
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5">
                        <ChipVia via={o.via} />
                        {o.bloqueantes > 0 && <AlertCircle size={14} className="text-marca" />}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right cifra font-medium">
                      {o.precio_propuesto
                        ? eurExacto(o.precio_propuesto)
                        : <span className="text-tinta-tenue font-normal">sin precio</span>}
                    </td>
                    <td className="px-4 py-3 text-right cifra text-tinta-tenue w-24">
                      {fechaCorta(o.fecha_entrega_comprometible)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </div>
    </>
  );
}
