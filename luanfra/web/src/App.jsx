import { Route, Routes } from "react-router-dom";
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

export default function App() {
  return (
    <Marco>
      <Routes>
        <Route path="/"             element={<PanelPrincipal />} />
        <Route path="/ofertas"      element={<Ofertas />} />
        <Route path="/ofertas/:id"  element={<FichaOferta />} />
        <Route path="/planos"       element={<EnObras nombre="Planos" />} />
        <Route path="/taller"       element={<EnObras nombre="Taller" />} />
        <Route path="/clientes"     element={<EnObras nombre="Clientes" />} />
        <Route path="/ajustes"      element={<EnObras nombre="Ajustes" />} />
      </Routes>
    </Marco>
  );
}
