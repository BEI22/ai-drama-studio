import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
    "./hooks/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Studio palette -- dark, film-adjacent, low chroma.
        ink: {
          950: "#08090d",
          900: "#0d0f14",
          850: "#12141b",
          800: "#181b24",
          700: "#232733",
          600: "#323847",
        },
        brand: {
          400: "#8b7dff",
          500: "#6d5cff",
          600: "#5a48f0",
        },
        accent: {
          400: "#4fd1c5",
          500: "#2bb3a7",
        },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      boxShadow: {
        panel: "0 1px 0 0 rgba(255,255,255,0.04) inset, 0 20px 40px -30px rgba(0,0,0,0.9)",
      },
    },
  },
  plugins: [],
};

export default config;
