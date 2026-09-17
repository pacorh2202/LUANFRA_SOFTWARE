import { useState } from "react";
import { comprobarAcceso, configurarAcceso } from "./api";
import { Route, Routes } from "react-router-dom";
import Planificador from "./vistas/Planificador";
import Marco from "./componentes/Marco";
import PanelPrincipal from "./vistas/PanelPrincipal";
import Ofertas from "./vistas/Ofertas";
import FichaOferta from "./vistas/FichaOferta";

const EnObras = ({ nombre }) => (
  <div className="p-6">
    <h1 className="text-xl font-semibold">{nombre}</h1>
    <p className="text-sm text-tinta-tenue mt-1">Pendiente de construir.</p>
  </div>
);

function Aplicacion() {
  return (
    <Marco>
      <Routes>
        <Route path="/"             element={<PanelPrincipal />} />
        <Route path="/ofertas"      element={<Ofertas />} />
        <Route path="/ofertas/:id"  element={<FichaOferta />} />
        <Route path="/planos"       element={<EnObras nombre="Planos" />} />
        <Route path="/taller"       element={<Planificador />} />
        <Route path="/clientes"     element={<EnObras nombre="Clientes" />} />
        <Route path="/ajustes"      element={<EnObras nombre="Ajustes" />} />
      </Routes>
    </Marco>
  );
}

export default function App() {
  const [usuario, setUsuario] = useState(null);
  const [clave, setClave] = useState("");
  const [error, setError] = useState("");
  const [cargando, setCargando] = useState(false);
  async function entrar(e) {
    e.preventDefault(); setCargando(true); setError(""); configurarAcceso(clave);
    try { const s = await comprobarAcceso(); setUsuario(s.usuario); setClave(""); }
    catch (e) { configurarAcceso(""); setError(e.message); }
    finally { setCargando(false); }
  }
  if (!usuario) return <main className="max-w-md mx-auto p-8">
    <h1 className="text-2xl font-semibold">Luanfra · Acceso al piloto</h1>
    <p className="my-4">Introduce tu clave personal de acceso.</p>
    <form onSubmit={entrar}>
      <label htmlFor="clave">Clave de acceso</label>
      <input id="clave" type="password" autoComplete="current-password" required
        value={clave} onChange={e => setClave(e.target.value)}
        className="block border rounded p-2 w-full my-3" />
      <button className="btn-prim" disabled={cargando}>{cargando ? "Comprobando…" : "Entrar"}</button>
      {error && <p role="alert" className="mt-4 text-red-700">{error}</p>}
    </form>
  </main>;
  return <><div className="px-4 py-2 flex justify-between border-b">
    <span>{usuario}</span><button onClick={() => {
      configurarAcceso(""); setUsuario(null); setClave("");
    }}>Cerrar sesión</button></div><Aplicacion /></>;
}
