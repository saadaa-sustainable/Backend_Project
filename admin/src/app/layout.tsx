import type { Metadata } from "next";
import { IBM_Plex_Sans, IBM_Plex_Mono } from "next/font/google";
import { AppNav } from "@/components/AppNav";
import { PageShell } from "@/components/PageShell";
import { SelectionProvider } from "@/lib/SelectionContext";
import "./globals.css";

/**
 * IBM Plex, per the approved foundations board (`Main.dc.html`):
 * Plex Sans for the interface, Plex Mono for every figure.
 *
 * The Vienna direction wants a figure to read as a measured thing, and
 * a grotesque with proportional numerals cannot do that on its own --
 * `font-variant-numeric` fixes the widths but not the register. Plex
 * Mono is applied by `.tabular-nums` in globals.css, which is already
 * on every numeral-bearing element on the surface, so the mono face
 * arrives everywhere a number does without a per-component edit.
 *
 * Weights are listed explicitly: neither Plex family ships as a
 * variable font through next/font/google, so an unlisted weight would
 * be synthesised by the browser rather than loaded.
 */
const plexSans = IBM_Plex_Sans({
  variable: "--font-plex-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Bronze/Silver Admin",
  description: "Schema browser and ingestion trigger for the medallion pipeline",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${plexSans.variable} ${plexMono.variable} h-full antialiased`}
    >
      <body className="flex h-full bg-bg-base font-sans text-text-primary">
        <SelectionProvider>
          <AppNav />
          <main className="min-w-0 flex-1 overflow-y-auto bg-bg-base">
            <PageShell>{children}</PageShell>
          </main>
        </SelectionProvider>
      </body>
    </html>
  );
}
