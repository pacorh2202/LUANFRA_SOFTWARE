/** Tokens de marca Luanfra: negro del logo + rojo del acento. */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        tinta:   { DEFAULT: "#14171A", suave: "#3A4149", tenue: "#6B7280" },
        marca:   { DEFAULT: "#D42A2A", oscuro: "#A81F1F", claro: "#FDECEC" },
        lienzo:  { DEFAULT: "#F6F7F9", card: "#FFFFFF" },
        borde:   { DEFAULT: "#E6E8EB", fuerte: "#D3D7DC" },
        exito:   { DEFAULT: "#16A34A", claro: "#ECFDF3" },
        aviso:   { DEFAULT: "#B45309", claro: "#FEF6E7" },
      },
      fontFamily: { sans: ["Inter", "system-ui", "Segoe UI", "sans-serif"] },
      boxShadow: { card: "0 1px 2px rgba(20,23,26,.04), 0 1px 3px rgba(20,23,26,.06)" },
      borderRadius: { card: "10px" },
    },
  },
  plugins: [],
};
