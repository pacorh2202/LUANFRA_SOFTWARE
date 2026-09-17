import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft, Check, Clock, FileText, Pencil, X, Mail, ShieldCheck,
} from "lucide-react";
import {
  Panel, Fila, Barra, ChipVia, ChipEstado, Aviso, Esqueleto, Vacio, Chip,
} from "../componentes/Base";
import { api, eurExacto, fecha, haceTiempo, horas, pct } from "../api";

export default function FichaOferta() {
  const { id } = useParams();
  const ir = useNavigate();
  const [o, setO] = useState(null);
  const [error, setError] = useState(null);
  const [editando, setEditando] = useState(false);
  const [aviso, setAviso] = useState(null);

  const cargar = () => api.oferta(id).then(setO).catch((e) => setError(e.message));
  useEffect(() => { setO(null); cargar(); }, [id]);

  async function accion(fn, mensaje) {
    try { await fn(); setAviso({ ok: true, txt: mensaje }); cargar(); }
    catch (e) { setAviso({ ok: false, txt: e.message }); }
  }

  if (error) return <div className="p-6"><Vacio titulo="No se pudo cargar" texto={error} /></div>;
  if (!o) return <div className="p-6 max-w-5xl"><Esqueleto filas={10} /></div>;

  const sinPrecio = o.precio_propuesto == null;
  const conf = Math.round((o.confianza ?? 0) * 100);
  const d = o.desglose ?? {};
  const margen = o.precio_propuesto && o.coste_calculado
    ? Math.round(((o.precio_propuesto - o.coste_calculado) / o.coste_calculado) * 100)
    : null;

  return (
    <div className="pb-16">
      {/* Cabecera */}
      <header className="px-6 pt-5 pb-4 border-b border-borde bg-white">
        <button onClick={() => ir(-1)}
          className="flex items-center gap-1.5 text-sm text-tinta-tenue hover:text-tinta mb-3">
          <ArrowLeft size={15} /> Ofertas
        </button>
        <div className="flex items-start justify-between gap-6">
          <div className="min-w-0">
            <div className="flex items-center gap-2.5 flex-wrap">
              <h1 className="text-xl font-semibold truncate">{o.cliente}</h1>
              <ChipVia via={o.via} />
              <ChipEstado estado={o.estado} />
            </div>
            <p className="text-sm text-tinta-tenue mt-1">
              {o.pieza_ref} · {o.pieza_desc} · {Math.round(o.cantidad)} unidades
            </p>
          </div>
          <div className="text-right shrink-0">
            <div className="etiqueta">Precio propuesto</div>
            <div className="text-3xl font-semibold cifra mt-0.5">
              {sinPrecio ? <span className="text-tinta-tenue text-xl">Sin precio</span>
                         : eurExacto(o.precio_propuesto)}
            </div>
            {!sinPrecio && (
              <div className="text-xs text-tinta-tenue cifra mt-0.5">
                Banda {eurExacto(o.precio_min)} — {eurExacto(o.precio_max)}
              </div>
            )}
          </div>
        </div>
      </header>

      {aviso && (
        <div className="px-6 pt-4">
          <div className={`text-sm px-3 py-2 rounded-lg ${aviso.ok
            ? "bg-exito-claro text-exito" : "bg-marca-claro text-marca"}`}>
            {aviso.txt}
          </div>
        </div>
      )}

      <div className="grid grid-cols-[1fr_360px] gap-4 px-6 py-4 items-start">
        {/* --------- Columna principal --------- */}
        <div className="space-y-4">
          {sinPrecio && (
            <Panel>
              <div className="p-4">
                <Aviso gravedad="bloqueante">
                  <strong>No propongo precio para esta pieza.</strong> Es nueva o el plano
                  tiene carencias que impiden calcular con honestidad. Abajo tienes el
                  expediente y las preguntas para el cliente.
                </Aviso>
              </div>
            </Panel>
          )}

          <Panel titulo="Desglose del coste"
                 accion={<span className="text-xs text-tinta-tenue">
                   modelo {o.version_modelo}</span>}>
            <div className="p-4 space-y-2.5">
              <Fila etiqueta="Material" valor={eurExacto(d.material)} />
              <Fila etiqueta="Máquina" valor={eurExacto(d.maquina)} />
              <Fila etiqueta="Preparación" valor={eurExacto(d.preparacion)} />
              <Fila etiqueta="Subcontratas" valor={eurExacto(d.externo)} />
              <Fila etiqueta="Indirectos" valor={eurExacto(d.indirectos)} />
              <div className="pt-2.5 border-t border-borde space-y-2.5">
                <Fila etiqueta="Coste total" valor={eurExacto(o.coste_calculado)} fuerte />
                <Fila etiqueta="Margen sobre coste"
                      valor={margen == null ? "—" : `${margen}%`} fuerte />
                <Fila etiqueta="Carga de máquina" valor={horas(d.minutos_totales)} tenue />
              </div>
            </div>
          </Panel>

          <Panel titulo="Piezas en las que me apoyo"
                 accion={<span className="text-xs text-tinta-tenue">
                   {o.comparables.length} comparables</span>}>
            {o.comparables.length === 0 ? (
              <Vacio titulo="Sin comparables"
                     texto="No he encontrado piezas parecidas en el histórico." />
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-tinta-tenue border-b border-borde">
                    <th className="font-medium px-4 py-2">Pieza</th>
                    <th className="font-medium px-4 py-2 text-right">Parecido</th>
                    <th className="font-medium px-4 py-2 text-right">Se ofertó</th>
                    <th className="font-medium px-4 py-2 text-right">Horas reales</th>
                    <th className="font-medium px-4 py-2 text-right">Resultado</th>
                  </tr>
                </thead>
                <tbody>
                  {o.comparables.map((c, i) => (
                    <tr key={i} className="border-b border-borde last:border-0">
                      <td className="px-4 py-2.5">
                        <div className="font-medium">{c.pieza}</div>
                        <div className="text-xs text-tinta-tenue">
                          {c.descripcion} · {haceTiempo(c.fecha_referencia)}
                        </div>
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <div className="w-14"><Barra pct={c.similitud * 100} tono="bg-tinta-suave" /></div>
                          <span className="cifra text-xs text-tinta-tenue w-9">{pct(c.similitud)}</span>
                        </div>
                      </td>
                      <td className="px-4 py-2.5 text-right cifra">{eurExacto(c.precio_historico)}</td>
                      <td className="px-4 py-2.5 text-right cifra text-tinta-tenue">
                        {horas(c.minutos_reales)}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        {c.resultado === "ganada" && <Chip tono="verde">ganada</Chip>}
                        {c.resultado === "perdida" && <Chip tono="rojo">perdida</Chip>}
                        {!["ganada", "perdida"].includes(c.resultado) &&
                          <Chip tono="gris">sin respuesta</Chip>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>

          {o.plano && (
            <Panel titulo="Revisión del plano"
                   accion={<span className="text-xs text-tinta-tenue flex items-center gap-1.5">
                     <FileText size={13} /> {o.plano.nombre_original}</span>}>
              <div className="p-4 space-y-2">
                {(o.plano.hallazgos ?? []).length === 0 ? (
                  <Aviso gravedad="menor">
                    No he encontrado problemas en los catorce puntos que reviso.
                    Eso no certifica que el plano esté completo.
                  </Aviso>
                ) : (
                  (o.plano.hallazgos ?? []).map((h, i) => (
                    <Aviso key={i} gravedad={h.gravedad}>{h.texto}</Aviso>
                  ))
                )}
                <div className="pt-2 flex items-center gap-4 text-xs text-tinta-tenue">
                  <span>Método: {o.plano.metodo?.replace("_", " ")}</span>
                  <span>Fiabilidad de la lectura: {pct(o.plano.confianza)}</span>
                  {!o.plano.es_vectorial && <span className="text-aviso">Plano escaneado</span>}
                </div>
              </div>
            </Panel>
          )}

          {o.hipotesis.length > 0 && (
            <Panel titulo="Hipótesis asumidas">
              <div className="p-4">
                <ul className="space-y-1.5 text-sm">
                  {o.hipotesis.map((h, i) => (
                    <li key={i} className="flex gap-2">
                      <span className="text-tinta-tenue">·</span>{h}
                    </li>
                  ))}
                </ul>
                <p className="mt-3 text-xs text-tinta-tenue">
                  Van escritas en la oferta. Si el cliente difiere, se revisa el precio.
                </p>
              </div>
            </Panel>
          )}

          {o.correcciones.length > 0 && (
            <Panel titulo="Correcciones que hiciste">
              <div className="divide-y divide-borde">
                {o.correcciones.map((c, i) => (
                  <div key={i} className="px-4 py-3 text-sm flex justify-between gap-4">
                    <div>
                      <div className="font-medium">{c.campo.replace(/_/g, " ")}</div>
                      {c.motivo && <div className="text-xs text-tinta-tenue mt-0.5">{c.motivo}</div>}
                    </div>
                    <div className="cifra text-right shrink-0">
                      <span className="text-tinta-tenue line-through">{c.valor_propuesto}</span>
                      <span className="mx-2 text-tinta-tenue">→</span>
                      <span className="font-medium">{c.valor_corregido}</span>
                    </div>
                  </div>
                ))}
              </div>
            </Panel>
          )}
        </div>

        {/* --------- Columna lateral --------- */}
        <div className="space-y-4 sticky top-4">
          <Panel titulo="Confianza">
            <div className="p-4">
              <div className="flex items-baseline justify-between mb-2">
                <span className="text-2xl font-semibold cifra">{conf}%</span>
                <ChipVia via={o.via} />
              </div>
              <Barra pct={conf} />
              <p className="mt-3 text-xs text-tinta-tenue leading-relaxed">
                {conf > 80 && "Pieza conocida y comparables sólidos. Puedes fiarte del número."}
                {conf > 55 && conf <= 80 && "Hay comparables, pero no exactos. Merece un vistazo al desglose."}
                {conf <= 55 && "Poco apoyo en el histórico. Esta la tienes que valorar tú."}
              </p>
            </div>
          </Panel>

          <Panel titulo="Plazo de entrega">
            <div className="p-4 space-y-3">
              <Fila etiqueta="Óptimo" valor={fecha(o.fecha_entrega_optima)} tenue />
              <Fila etiqueta="Comprometible" valor={fecha(o.fecha_entrega_comprometible)} fuerte />
              <p className="text-xs text-tinta-tenue flex gap-1.5 pt-1 leading-relaxed">
                <Clock size={13} className="shrink-0 mt-0.5" />
                Al cliente se le da la fecha comprometible: es la que se cumple
                ocho de cada diez veces.
              </p>
            </div>
          </Panel>

          <Panel titulo="Petición original">
            <div className="p-4 space-y-2 text-sm">
              <Fila etiqueta="De" valor={o.peticion.remitente ?? "—"} />
              <Fila etiqueta="Recibida" valor={fecha(o.peticion.recibido_en)} />
              <p className="text-xs text-tinta-tenue pt-1 flex gap-1.5">
                <Mail size={13} className="shrink-0 mt-0.5" />
                {o.peticion.asunto}
              </p>
            </div>
          </Panel>

          {/* Acciones */}
          {o.estado === "borrador" ? (
            <div className="space-y-2">
              <div className="flex gap-2">
                <button
                  onClick={() => accion(() => api.aprobar(o.id), "Oferta marcada como revisada.")}
                  disabled={sinPrecio}
                  className="btn-prim flex-1 justify-center disabled:opacity-40 disabled:cursor-not-allowed">
                  <Check size={16} /> Aprobar
                </button>
                <button onClick={() => setEditando((v) => !v)} className="btn-sec">
                  <Pencil size={15} /> Corregir
                </button>
              </div>
              {editando && (
                <FormularioCorreccion
                  oferta={o}
                  onGuardar={(c) => accion(() => api.corregir(o.id, c), "Corrección guardada.")
                    .then(() => setEditando(false))}
                />
              )}
              <button
                onClick={() => accion(() => api.descartar(o.id), "Oferta descartada.")}
                className="btn-sec w-full justify-center text-tinta-tenue">
                <X size={15} /> Descartar
              </button>
              <p className="text-xs text-tinta-tenue text-center leading-relaxed pt-1">
                Aprobar no envía nada. El correo al cliente lo mandas tú.
              </p>
            </div>
          ) : (
            <div className="card p-4 flex gap-2.5">
              <ShieldCheck size={16} className="text-exito shrink-0 mt-0.5" />
              <p className="text-xs leading-relaxed">
                Esta oferta ya está <strong>{o.estado}</strong>. Cualquier cambio a partir
                de aquí queda registrado en la auditoría.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function FormularioCorreccion({ oferta, onGuardar }) {
  const [precio, setPrecio] = useState(oferta.precio_propuesto ?? "");
  const [motivo, setMotivo] = useState("");
  const minimo = oferta.coste_calculado;

  const invalido = precio !== "" && minimo && Number(precio) < Number(minimo);

  return (
    <div className="card p-4 space-y-3">
      <div>
        <label className="etiqueta">Precio corregido</label>
        <input type="number" step="0.01" value={precio}
          onChange={(e) => setPrecio(e.target.value)}
          className="mt-1 w-full h-9 px-3 rounded-lg border border-borde text-sm cifra
                     focus:outline-none focus:ring-2 focus:ring-tinta/10" />
        {invalido && (
          <p className="mt-1 text-xs text-marca">
            No puede quedar por debajo del coste ({eurExacto(minimo)}).
          </p>
        )}
      </div>
      <div>
        <label className="etiqueta">Por qué lo cambias</label>
        <input value={motivo} onChange={(e) => setMotivo(e.target.value)}
          placeholder="Cliente habitual, pieza urgente…"
          className="mt-1 w-full h-9 px-3 rounded-lg border border-borde text-sm
                     placeholder:text-tinta-tenue focus:outline-none focus:ring-2 focus:ring-tinta/10" />
        <p className="mt-1 text-xs text-tinta-tenue leading-relaxed">
          Esto es lo que enseña al sistema tu criterio. Merece una línea.
        </p>
      </div>
      <button
        onClick={() => onGuardar({ precio: Number(precio), motivo })}
        disabled={invalido || precio === ""}
        className="btn-marca w-full justify-center disabled:opacity-40">
        Guardar corrección
      </button>
    </div>
  );
}
