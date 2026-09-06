import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "NEXUS", description: "AI software-engineering command center" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-[#0a0e14] text-zinc-100 antialiased">{children}</body>
    </html>
  );
}
