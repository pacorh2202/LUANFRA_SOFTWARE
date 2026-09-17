import { useState } from "react";
import { api } from "../api";

const centroNuevo = () => ({ centro: "", horas_dia_teoricas: 8,
  factor_disponibilidad: 0.7, minutos_comprometidos: 0 });
const cargaNueva = () => ({ centro: "", minutos: 0, plazo_externo_dias: 0 });

export default function Planificador() {
  const [centros, setCentros] = useState([centroNuevo()]);
  const [cargas, setCargas] = useState([cargaNueva()]);
  const [desde, setDesde] = useState(new Date().toLocaleDateString("en-CA"));
  const [colchon, setColchon] = useState(50);
  const [festivos, setFestivos] = useState("");
  const [resultado, setResultado] = useState(null);
  const [error, setError] = useState("");
  const [calculando, setCalculando] = useState(false);
  function cambiar(lista, setter, i, campo, valor) {
    setter(lista.map((r, n) => n === i ? { ...r, [campo]: valor } : r));
    setResultado(null);
  }
  function numero(lista, setter, fila, i, campo, titulo, min, max, step = 1) {
    return <label className="block text-sm">{titulo}
      <input aria-label={`${titulo} ${i + 1}`} className="block border rounded p-2 w-full"
        type="number" required min={min} max={max} step={step} value={fila[campo]}
        onChange={e => cambiar(lista, setter, i, campo, e.target.value)} />
    </label>;
  }
  async function calcular(e) {
    e.preventDefault(); setCalculando(true); setError(""); setResultado(null);
    try {
      const r = await api.plazo({ desde, colchon_pct: Number(colchon),
        festivos: festivos.split(",").map(x => x.trim()).filter(Boolean),
        colas: centros.map(c => ({ ...c, horas_dia_teoricas: Number(c.horas_dia_teoricas),
          factor_disponibilidad: Number(c.factor_disponibilidad),
          minutos_comprometidos: Number(c.minutos_comprometidos) })),
        cargas: cargas.map(c => ({ ...c, minutos: Number(c.minutos),
          plazo_externo_dias: Number(c.plazo_externo_dias) })),
      });
      setResultado(r);
    } catch(e) { setError(e.message); }
    finally { setCalculando(false); }
  }
  return <main className="p-6 max-w-5xl space-y-5">
    <h1 className="text-2xl font-semibold">Simulador de plazo</h1>
    <p>Introduce la cola pendiente y las operaciones en orden. Cada operación espera al lote
      completo de la anterior. Se excluyen sábados, domingos y festivos indicados.</p>
    <p className="text-sm">Las 8 horas y el 70 % iniciales son valores editables para simular.
      Confirma la capacidad de cada máquina. No se añaden horas desatendidas automáticamente.</p>
    <form onSubmit={calcular} className="space-y-5">
      <div className="grid md:grid-cols-3 gap-4">
        <label>Fecha de referencia<input aria-label="Fecha de referencia" type="date" required
          value={desde} onChange={e => { setDesde(e.target.value); setResultado(null); }}
          className="block border p-2 rounded" /></label>
        <label>Colchón (%)<input type="number" min="0" required value={colchon}
          onChange={e => { setColchon(e.target.value); setResultado(null); }}
          className="block border p-2 rounded" /></label>
        <label>Festivos (AAAA-MM-DD, separados por coma)<input value={festivos}
          onChange={e => { setFestivos(e.target.value); setResultado(null); }}
          className="block border p-2 rounded w-full" /></label>
      </div>
      <h2 className="font-semibold">Capacidad por máquina</h2>
      {centros.map((c, i) => <div key={i} className="grid md:grid-cols-5 gap-3 border p-3 rounded">
        <label>Código<input required aria-label={`Código máquina ${i + 1}`} value={c.centro}
          onChange={e => cambiar(centros, setCentros, i, "centro", e.target.value.trim())}
          className="block border p-2 rounded w-full" /></label>
        {numero(centros, setCentros, c, i, "horas_dia_teoricas", "Horas diarias", 0.1, 24, 0.1)}
        {numero(centros, setCentros, c, i, "factor_disponibilidad", "Disponibilidad (0–1)", 0.01, 1, 0.01)}
        {numero(centros, setCentros, c, i, "minutos_comprometidos", "Cola pendiente (min)", 0)}
        <button type="button" disabled={centros.length === 1} onClick={() => {
          setCentros(centros.filter((_, n) => n !== i)); setResultado(null);
        }}>Quitar máquina</button>
      </div>)}
      <button type="button" className="btn-sec" onClick={() => {
        setCentros([...centros, centroNuevo()]); setResultado(null);
      }}>Añadir máquina</button>
      <h2 className="font-semibold">Operaciones en secuencia</h2>
      {cargas.map((c, i) => <div key={i} className="grid md:grid-cols-4 gap-3 border p-3 rounded">
        <label>Máquina / proveedor · paso {i + 1}<input required value={c.centro}
          aria-label={`Máquina operación ${i + 1}`} className="block border p-2 rounded w-full"
          onChange={e => cambiar(cargas, setCargas, i, "centro", e.target.value.trim())} /></label>
        {numero(cargas, setCargas, c, i, "minutos", "Minutos del lote, incluida preparación", 0)}
        {numero(cargas, setCargas, c, i, "plazo_externo_dias", "Días laborables externos", 0)}
        <button type="button" disabled={cargas.length === 1} onClick={() => {
          setCargas(cargas.filter((_, n) => n !== i)); setResultado(null);
        }}>Quitar operación</button>
      </div>)}
      <p className="text-sm">Para una subcontrata, introduce días externos y deja sus minutos en cero.</p>
      <button type="button" className="btn-sec" onClick={() => {
        setCargas([...cargas, cargaNueva()]); setResultado(null);
      }}>Añadir operación</button>
      <button disabled={calculando} className="btn-prim ml-3">{calculando ? "Calculando…" : "Simular plazo"}</button>
    </form>
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {resultado && <section aria-live="polite" className="border rounded p-5 bg-white space-y-2">
      <h2 className="font-semibold">Resultado de la simulación</h2>
      <p>Fecha estimada: <strong>{resultado.fecha_optima}</strong> · {resultado.dias_optimo} días laborables</p>
      <p>Fecha con colchón: <strong>{resultado.fecha_comprometible}</strong></p>
      <p>Centro con mayor carga relativa: {resultado.centro_cuello_botella}</p>
      <p className="text-sm">Estimación por colas. No reserva máquinas, no identifica los pedidos
        desplazados y no garantiza una probabilidad de entrega.</p>
    </section>}
  </main>;
}
