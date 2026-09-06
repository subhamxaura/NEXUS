import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "NEXUS", description: "AI software-engineering command center" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-[#0a0e14] text-zinc-100 antialiased">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-zinc-100 focus:px-3 focus:py-2 focus:text-sm focus:text-zinc-900"
        >
          Skip to content
        </a>
        <div id="main">{children}</div>
      </body>
    </html>
  );
}
