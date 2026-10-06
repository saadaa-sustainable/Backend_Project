"use client";

import { usePathname } from "next/navigation";

/**
 * The page container, which decides how wide a route is allowed to get.
 *
 * The /user routes are dense dashboards -- the Landing Page Analysis
 * table alone is 16 columns -- so capping them at 1600px leaves most of
 * a wide monitor empty and makes the table scroll sideways while blank
 * space sits either side of it. They run full width instead.
 *
 * The admin routes keep the cap. They are forms, logs and prose, which
 * get harder to read the wider the measure gets, not easier.
 *
 * Branching on the path here mirrors AppNav, which already picks the
 * sidebar the same way -- the alternative is restructuring every admin
 * route into a Next.js route group just to get a second <main>.
 */
export function PageShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const fullWidth = pathname?.startsWith("/user") ?? false;
  return (
    <div className={`w-full px-8 py-8 ${fullWidth ? "" : "mx-auto max-w-[1600px]"}`}>
      {children}
    </div>
  );
}
