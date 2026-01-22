/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Sora", "Work Sans", "sans-serif"],
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
