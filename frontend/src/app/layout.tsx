import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import ClientShell from "./ClientShell";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Project SCION — Structural Change Intelligence",
  description: "Monitor structural changes, assess impact, and get AI-powered risk recommendations across your data warehouse.",
};

// Root layout is a Server Component by default (no "use client"). All
// client-only state (providers, sidebar, toasts) lives inside <ClientShell>.
// Keeping this file minimal lets Next.js stream the shell fast and keeps the
// client bundle small.
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full">
        <ClientShell>{children}</ClientShell>
      </body>
    </html>
  );
}
