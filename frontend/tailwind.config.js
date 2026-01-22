/** @type {import('tailwindcss').Config} */
export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        // Use a font with Cyrillic support; avoids "????" for Russian.
        sans: ["Rubik", "system-ui", "sans-serif"],
      },
      colors: {
        panel: "#111827",
        card: "#1f2937",
        accent: "#f59e0b"
      },
    },
  },
  plugins: [],
};
