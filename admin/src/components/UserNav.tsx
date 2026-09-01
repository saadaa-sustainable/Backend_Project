"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * Left sidebar for the /user analytics panel — kwikengage.ai visual
 * pattern (dark navy bg, categorized nav with small uppercase section
 * headers, small colored icon square per item, subtle active highlight).
 *
 * Structure choice: kwikengage groups a lot of features into 4 broad
 * areas (Marketing & Retention, Audience, Chats, Report & Logs). We have
 * fewer routes so 3 sections is the natural fit — one per functional
 * intent (analytics vs. data pipes vs. tools). Each item carries a small
 * colored icon square that echoes kwikengage's colored circles on their
 * KPI cards, so the color language reads consistent between sidebar and
 * content.
 */

interface NavItem {
  href: string;
  label: string;
  icon: string;
  /** Tailwind bg-* class for the icon square; picked to echo the
   * kwikengage KPI-card icon palette (each functional group gets a
   * distinct color family). */
  iconBg: string;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    label: "OVERVIEW",
    items: [
      { href: "/user", label: "Home", icon: "▦", iconBg: "bg-[#4A5AD9]" },
      { href: "/user/analytics", label: "Analytics", icon: "▲", iconBg: "bg-[#5B4FBF]" },
    ],
  },
  {
    label: "DATA",
    items: [
      { href: "/user/fetch", label: "Fetch Status", icon: "⇄", iconBg: "bg-[#D97706]" },
      { href: "/user/schema", label: "Schema Browser", icon: "▤", iconBg: "bg-[#2E7D32]" },
      { href: "/user/computational", label: "Computational Layer", icon: "◫", iconBg: "bg-[#0891B2]" },
    ],
  },
  {
    label: "TOOLS",
    items: [
      { href: "/user/assistant", label: "AI Assistant", icon: "✳", iconBg: "bg-[#DB2777]" },
    ],
  },
];

export function UserNav() {
  const pathname = usePathname();

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-sb-border bg-sb-bg">
      {/* Logo -- small colored square + product name. Small "NEW" badge
          mirrors kwikengage's "Kwik.AI" NEW badge treatment. */}
      <Link href="/user" className="flex items-center gap-2.5 px-5 pt-5 pb-6">
        <span className="flex h-8 w-8 items-center justify-center rounded-md bg-accent-yellow text-sm font-bold text-white shadow-sm">
          S
        </span>
        <div className="flex items-baseline gap-2">
          <span className="text-[15px] font-semibold tracking-tight text-white">Saadaa</span>
          <span className="rounded-sm bg-[#E85D3B] px-1.5 py-[1px] text-[9px] font-bold tracking-wide text-white">
            LIVE
          </span>
        </div>
      </Link>

      <nav className="flex flex-1 flex-col gap-4 overflow-y-auto px-3 pb-4">
        {NAV_GROUPS.map((group) => (
          <div key={group.label} className="flex flex-col gap-0.5">
            <div className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-sb-section">
              {group.label}
            </div>
            {group.items.map((item) => {
              const active =
                item.href === "/user"
                  ? pathname === "/user"
                  : pathname?.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[13px] font-medium transition-colors ${
                    active
                      ? "bg-sb-surface text-white"
                      : "text-sb-text hover:bg-sb-surface/60 hover:text-white"
                  }`}
                >
                  <span
                    className={`flex h-5 w-5 shrink-0 items-center justify-center rounded ${item.iconBg} text-[10px] text-white`}
                    aria-hidden
                  >
                    {item.icon}
                  </span>
                  <span className="truncate">{item.label}</span>
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      <div className="border-t border-sb-border px-3 py-3">
        <Link
          href="/"
          className="flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[12px] font-medium text-sb-text-muted transition-colors hover:bg-sb-surface/60 hover:text-white"
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
