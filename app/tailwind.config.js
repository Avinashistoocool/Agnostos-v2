/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: "#16171b", 900: "#121317", 800: "#16171b" },
        surface: { DEFAULT: "#1e2026", 2: "#23262d", 3: "#292c34" },
        line: { DEFAULT: "#2a2d35", strong: "#363a44" },
        cream: { DEFAULT: "#f4efe6", dim: "#d9d3c8" },
        rust: { DEFAULT: "#b5452e", hover: "#c9583f", soft: "rgba(181,69,46,0.14)" },
        slate: { DEFAULT: "#8b93a1", dim: "#6b7280" },
        sage: { DEFAULT: "#7fa37a", soft: "rgba(127,163,122,0.14)" },
        amber: { DEFAULT: "#d6a243", soft: "rgba(214,162,67,0.14)" },
      },
      fontFamily: {
        serif: ['"Source Serif 4 Variable"', "Georgia", "serif"],
        sans: ['"Inter"', "system-ui", "Segoe UI", "sans-serif"],
        mono: ['"Cascadia Code"', "Consolas", "ui-monospace", "monospace"],
      },
      boxShadow: {
        card: "0 1px 0 rgba(255,255,255,0.03) inset, 0 8px 24px -12px rgba(0,0,0,0.5)",
        pop: "0 20px 50px -12px rgba(0,0,0,0.7)",
      },
      keyframes: {
        "fade-in": { from: { opacity: 0, transform: "translateY(4px)" }, to: { opacity: 1, transform: "none" } },
        shimmer: { "100%": { transform: "translateX(100%)" } },
        "slide-in": { from: { transform: "translateX(24px)", opacity: 0 }, to: { transform: "none", opacity: 1 } },
      },
      animation: {
        "fade-in": "fade-in .22s ease-out both",
        "slide-in": "slide-in .22s ease-out both",
      },
    },
  },
  plugins: [],
};
