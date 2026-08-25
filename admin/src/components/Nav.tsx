"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/schema", label: "Schema Browser" },
  { href: "/build", label: "Build Table" },
  { href: "/customize", label: "Customise Columns" },
  { href: "/assistant", label: "AI Assistant" },
  { href: "/fetch", label: "Fetch Trigger" },
  { href: "/errors", label: "Error Logs" },
  { href: "/cron", label: "Cron / Sync Status" },
];

export function Nav() {
  const pathname = usePathname();

  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-6xl items-center gap-8 px-6 py-4">
        <Link href="/" className="flex items-center gap-2 text-sm font-semibold tracking-tight text-slate-900">
          <span className="flex h-6 w-6 items-center justify-center rounded bg-sky-600 text-xs text-white">
            ❄
          </span>
          Bronze/Silver Admin
        </Link>
        <nav className="flex gap-1 overflow-x-auto">
          {LINKS.map((link) => {
            const active = pathname?.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                className={`whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  active
                    ? "bg-sky-50 text-sky-700"
                    : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                }`}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
