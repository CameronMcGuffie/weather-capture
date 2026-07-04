/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        accent: {
          500: "#38bdf8",
          600: "#0ea5e9",
        },
      },
    },
  },
  plugins: [],
};
