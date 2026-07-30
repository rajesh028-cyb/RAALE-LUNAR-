import type { Metadata } from "next";
import localFont from "next/font/local";
import Link from "next/link";
import "./globals.css";

const geistSans = localFont({
  src: "./fonts/GeistVF.woff",
  variable: "--font-geist-sans",
  weight: "100 900",
});

const geistMono = localFont({
  src: "./fonts/GeistMonoVF.woff",
  variable: "--font-geist-mono",
  weight: "100 900",
});

export const metadata: Metadata = {
  title: "RAALE — Graph CSV Ingestion & Query Engine",
  description:
    "Upload CSV files, stream rows into Neo4j through Kafka, and ask natural-language questions answered directly from your graph data — zero hallucination, fully grounded.",
  keywords: ["Neo4j", "CSV", "Kafka", "graph database", "chatbot", "data ingestion"],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased bg-slate-950 text-slate-100`}>
        <nav className="relative z-50 border-b border-slate-800 bg-slate-950/80 backdrop-blur sticky top-0">
          <div className="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between">
            <Link href="/" className="text-base font-extrabold tracking-widest bg-clip-text text-transparent
              bg-gradient-to-r from-violet-400 via-purple-300 to-cyan-400">
              RAALE
            </Link>
            <div className="flex items-center gap-6 text-xs font-semibold text-slate-400">
              <Link href="/" className="hover:text-violet-300 transition-colors">Dashboard</Link>
              <Link href="/chat" className="hover:text-cyan-300 transition-colors">Chat</Link>
              <Link href="/report" className="hover:text-emerald-300 transition-colors">Report</Link>
            </div>
          </div>
        </nav>
        {children}
      </body>
    </html>
  );
}
