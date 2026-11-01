import type { Confidence } from "@trustdesk/sdk";
import { useId, useState } from "react";

import { strings } from "../lib/i18n";

const BARS: Record<Confidence, number> = { low: 1, medium: 2, high: 3 };
const COLOR: Record<Confidence, string> = { low: "bg-warning", medium: "bg-accent", high: "bg-success" };

/** Small accessible indicator. The tooltip explains what confidence means; raw scores are never shown. */
export function ConfidenceMeter({ level, lang }: { level: Confidence; lang: string }) {
  const t = strings(lang);
  const tipId = useId();
  const [open, setOpen] = useState(false);
  const filled = BARS[level];
  return (
    <span className="relative inline-flex">
      <button
        type="button"
        className="inline-flex items-center gap-1.5 rounded-full px-1 text-xs text-muted"
        aria-describedby={tipId}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        data-testid="confidence"
        data-level={level}
      >
        <span aria-hidden="true" className="flex items-end gap-0.5">
          {[1, 2, 3].map((n) => (
            <span key={n} className={`w-1 rounded-sm ${n <= filled ? COLOR[level] : "bg-border"}`} style={{ height: 4 + n * 3 }} />
          ))}
        </span>
        {t.confidence[level]}
      </button>
      <span
        id={tipId}
        role="tooltip"
        className={`absolute bottom-full start-0 z-10 mb-1 w-60 rounded-lg border border-border-strong bg-card p-2 text-xs text-body shadow-lg ${open ? "" : "td-sr-only"}`}
      >
        {t.confidenceHelp}
      </span>
    </span>
  );
}
