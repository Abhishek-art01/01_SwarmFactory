/**
 * tailwind.config.ts
 * Tailwind CSS v3 configuration for the Swarm Factory frontend.
 */

import type { Config } from "tailwindcss";

const config: Config = {
  // What does this do? Tells Tailwind which files to scan for class names
  // so unused styles are purged in production builds.
  content: [
    "./index.html",
    "./src/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        // Monospace stack used throughout the dashboard
        mono: [
          "JetBrains Mono",
          "Fira Code",
          "Cascadia Code",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "monospace",
        ],
      },
      colors: {
        // Semantic aliases so we can write text-brand-cyan etc. if needed
        brand: {
          cyan:    "rgb(6, 182, 212)",
          dark:    "#030810",
          surface: "#070e17",
          panel:   "#040b10",
        },
      },
      animation: {
        // Slightly faster pulse for the "running" agent dot
        pulse: "pulse 1.4s cubic-bezier(0.4, 0, 0.6, 1) infinite",
      },
      keyframes: {
        pulse: {
          "0%, 100%": { opacity: "1" },
          "50%":       { opacity: "0.35" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
