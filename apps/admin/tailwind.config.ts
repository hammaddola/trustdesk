import type { Config } from "tailwindcss";

const c = (v: string) => `rgb(var(--${v}) / <alpha-value>)`;

export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: c("bg"),
        raised: c("raised"),
        card: c("card"),
        heading: c("heading"),
        body: c("body"),
        muted: c("muted"),
        border: c("border"),
        "border-strong": c("border-strong"),
        accent: c("accent"),
        "accent-fg": c("accent-fg"),
        success: c("success"),
        warning: c("warning"),
        danger: c("danger"),
      },
    },
  },
} satisfies Config;
