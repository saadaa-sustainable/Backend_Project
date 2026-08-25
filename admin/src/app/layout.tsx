import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Nav } from "@/components/Nav";
import { SelectionProvider } from "@/lib/SelectionContext";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Bronze/Silver Admin",
  description: "Schema browser and ingestion trigger for the medallion pipeline",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-slate-50 font-sans text-slate-900">
        <SelectionProvider>
          <Nav />
          <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8">{children}</main>
        </SelectionProvider>
      </body>
    </html>
  );
}
