"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "./ui";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/sources", label: "Sources" },
  { href: "/conversations", label: "Conversations" },
  { href: "/leads", label: "Leads" },
  { href: "/insights", label: "Insights" },
  { href: "/playground", label: "Playground" },
  { href: "/settings", label: "Settings" },
];

export function NavLinks() {
  const path = usePathname();
  return (
    <nav aria-label="Main" className="flex gap-1 overflow-x-auto md:flex-col">
      {LINKS.map((l) => {
        const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
        return (
          <Link
            key={l.href}
            href={l.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "whitespace-nowrap rounded-lg px-3 py-2 text-sm transition-colors duration-200",
              active ? "bg-card font-medium text-heading" : "text-body hover:bg-card/60 hover:text-heading",
            )}
          >
            {l.label}
          </Link>
        );
      })}
    </nav>
  );
}
