/** @type {import('tailwindcss').Config} */
// Colors are the validated dark-mode palette from the data-viz design system.
// Semantic names keep components readable and the palette swappable in one place.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        plane: "#0d0d0d", // page background
        surface: "#1a1a19", // card surface
        "surface-2": "#232322", // raised surface
        ink: "#ffffff", // primary text
        "ink-secondary": "#c3c2b7",
        muted: "#898781", // axis / labels
        grid: "#2c2c2a", // hairline gridline
        hairline: "rgba(255,255,255,0.10)",
        series: "#3987e5", // categorical slot 1 (blue)
        "series-warm": "#eda100", // temperature accent (amber)
        good: "#0ca30c",
        warning: "#fab219",
        serious: "#ec835a",
        critical: "#d03b3b",
      },
      fontFamily: {
        sans: ['system-ui', '-apple-system', '"Segoe UI"', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
