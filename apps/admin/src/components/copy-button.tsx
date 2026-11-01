"use client";

import { useState } from "react";

export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 2000);
        } catch {
          setCopied(false);
        }
      }}
      className="inline-flex h-8 items-center rounded-lg bg-accent px-3 text-xs font-medium text-accent-fg"
    >
      {copied ? "Copied ✓" : "Copy embed code"}
    </button>
  );
}
