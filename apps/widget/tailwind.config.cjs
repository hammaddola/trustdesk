/** Styles are compiled into a string and injected into the widget's shadow root only. */
module.exports = {
  content: ["./src/**/*.{ts,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        primary: "rgb(var(--td-primary) / <alpha-value>)",
        "primary-fg": "rgb(var(--td-primary-fg) / <alpha-value>)",
        accent: "rgb(var(--td-accent) / <alpha-value>)",
        bg: "rgb(var(--td-bg) / <alpha-value>)",
        surface: "rgb(var(--td-surface) / <alpha-value>)",
        text: "rgb(var(--td-text) / <alpha-value>)",
        muted: "rgb(var(--td-muted) / <alpha-value>)",
        border: "rgb(var(--td-border) / <alpha-value>)",
        "border-strong": "rgb(var(--td-border-strong) / <alpha-value>)",
        card: "rgb(var(--td-card) / <alpha-value>)",
        body: "rgb(var(--td-body) / <alpha-value>)",
        success: "rgb(var(--td-success) / <alpha-value>)",
        warning: "rgb(var(--td-warning) / <alpha-value>)",
        error: "rgb(var(--td-error) / <alpha-value>)",
      },
      borderRadius: { panel: "20px" },
      fontFamily: { sans: ["var(--td-font)"] },
    },
  },
  corePlugins: { preflight: true },
};
