import { NavLink } from "react-router-dom";
import { LayoutDashboard, FileText, Factory, Users, Settings, FileSearch } from "lucide-react";

const MENU = [
  { a: "/",          icono: LayoutDashboard, txt: "Panel" },
  { a: "/ofertas",   icono: FileText,        txt: "Ofertas" },
  { a: "/planos",    icono: FileSearch,      txt: "Planos" },
  { a: "/taller",    icono: Factory,         txt: "Taller" },
  { a: "/clientes",  icono: Users,           txt: "Clientes" },
];

export default function Marco({ children }) {
  return (
    <div className="min-h-screen flex">
      {/* Sidebar: solo iconos, como Holded. Sin ruido. */}
      <nav className="w-14 bg-white border-r border-borde flex flex-col items-center py-3 gap-1 shrink-0">
        <div className="w-8 h-8 rounded-lg bg-tinta grid place-items-center mb-3">
          <span className="text-marca text-base font-bold leading-none">L</span>
        </div>
        {MENU.map(({ a, icono: I, txt }) => (
          <NavLink key={a} to={a} title={txt} end={a === "/"}
            className={({ isActive }) =>
              `w-9 h-9 grid place-items-center rounded-lg transition ${
                isActive ? "bg-marca-claro text-marca" : "text-tinta-tenue hover:bg-lienzo hover:text-tinta"
              }`}>
            <I size={18} strokeWidth={1.8} />
          </NavLink>
        ))}
        <div className="mt-auto">
          <NavLink to="/ajustes" title="Ajustes"
            className="w-9 h-9 grid place-items-center rounded-lg text-tinta-tenue hover:bg-lienzo">
            <Settings size={18} strokeWidth={1.8} />
          </NavLink>
        </div>
      </nav>
      <main className="flex-1 min-w-0">{children}</main>
    </div>
  );
}

export function Cabecera({ titulo, subtitulo, derecha }) {
  return (
    <header className="flex items-start justify-between px-6 pt-5 pb-4">
      <div>
        <h1 className="text-xl font-semibold">{titulo}</h1>
        {subtitulo && <p className="text-sm text-tinta-tenue mt-0.5">{subtitulo}</p>}
      </div>
      {derecha}
    </header>
  );
}
