import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { AppNav } from "@/components/AppNav";
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
      <body className="flex h-full bg-bg-base font-sans text-text-primary">
        <SelectionProvider>
          <AppNav />
          <main className="min-w-0 flex-1 overflow-y-auto bg-bg-base">
            <div className="mx-auto w-full max-w-[1600px] px-8 py-8">{children}</div>
          </main>
        </SelectionProvider>
      </body>
    </html>
  );
}
