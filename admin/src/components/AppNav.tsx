"use client";

import { usePathname } from "next/navigation";
import { Nav } from "./Nav";
import { UserNav } from "./UserNav";

// Root layout.tsx renders one <main> wrapper for every route -- swapping
// the header between the admin Nav and the read-only UserNav here (instead
// of via a nested /user/layout.tsx) avoids restructuring every existing
// admin route into a Next.js route group just to get two independent
// <main> slots.
export function AppNav() {
  const pathname = usePathname();
  return pathname?.startsWith("/user") ? <UserNav /> : <Nav />;
}
