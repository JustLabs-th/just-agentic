import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "just-agentic",
  description: "Secure Multi-Agent Team",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="bg-zinc-950 text-zinc-100 min-h-screen font-mono">
        {children}
      </body>
    </html>
  );
}
