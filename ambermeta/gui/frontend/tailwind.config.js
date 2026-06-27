/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        app: "#FAFAF9",
        surface: "#FFFFFF",
        hairline: "#E6E6E3",
        ink: { DEFAULT: "#1C1C1A", secondary: "#6B6B66", muted: "#9A9A95" },
        accent: { DEFAULT: "#2F66D0", subtle: "#EAF1FC" },
        valid: "#15803D",
        warning: "#B45309",
        error: "#B91C1C",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "monospace"],
      },
      fontSize: {
        xs: ["12px", "16px"],
        sm: ["13px", "18px"],
        base: ["14px", "20px"],
        lg: ["16px", "24px"],
        xl: ["20px", "28px"],
      },
    },
  },
  plugins: [],
};
