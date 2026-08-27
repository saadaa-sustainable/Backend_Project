"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/user", label: "Overview", icon: "▦" },
  { href: "/user/fetch", label: "Fetch Status", icon: "⇄" },
  { href: "/user/schema", label: "Schema Browser", icon: "▤" },
  { href: "/user/computational", label: "Computational Layer", icon: "◫" },
  { href: "/user/assistant", label: "AI Assistant", icon: "✳" },
  { href: "/user/analytics", label: "Analytics", icon: "📊" },
];

/** Persistent left sidebar -- dark slate, icon + label nav, active item
 * gets a left accent bar + tinted background. Same structural pattern as
 * Snowsight/Databricks' workspace sidebar: full-height, fixed width,
 * content area scrolls independently. */
export function UserNav() {
  const pathname = usePathname();

  return (
    <aside className="flex h-full w-60 shrink-0 flex-col border-r border-sb-border bg-sb-bg">
      <Link href="/user" className="flex items-center gap-2.5 px-5 py-5">
        <span className="flex h-7 w-7 items-center justify-center rounded-md bg-accent-yellow text-sm font-bold text-white">
          A
        </span>
        <span className="text-sm font-semibold tracking-tight text-white">Ads Dashboard</span>
      </Link>

      <nav className="flex flex-1 flex-col gap-0.5 overflow-y-auto px-3 pb-4">
        {LINKS.map((link) => {
          const active = link.href === "/user" ? pathname === "/user" : pathname?.startsWith(link.href);
          return (
            <Link
              key={link.href}
              href={link.href}
              className={`flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                active
                  ? "bg-sb-surface text-white"
                  : "text-sb-text hover:bg-sb-surface/60 hover:text-white"
              }`}
            >
              <span className="w-4 text-center text-xs opacity-80" aria-hidden>
                {link.icon}
              </span>
              {link.label}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-sb-border px-3 py-3">
        <Link
          href="/"
          className="flex items-center gap-2.5 rounded-md px-3 py-2 text-xs font-medium text-sb-text-muted transition-colors hover:bg-sb-surface/60 hover:text-white"
        >
          <span className="w-4 text-center" aria-hidden>
            ⇥
          </span>
          Switch to Admin
        </Link>
      </div>
    </aside>
  );
}
