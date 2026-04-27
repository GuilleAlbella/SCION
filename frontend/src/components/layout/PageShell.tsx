"use client";

import Header from "./Header";
import { usePathname } from "next/navigation";

interface PageShellProps {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}

/**
 * PageShell — shared chrome for every route. Wraps children with the page
 * Header and an animated <main>. The `key={pathname}` trick forces React
 * to unmount/remount <main> on route change, so the page-in animation
 * replays each time the user navigates.
 */
export default function PageShell({ title, subtitle, children }: PageShellProps) {
  const pathname = usePathname();

  return (
    <div className="flex-1 flex flex-col min-h-screen">
      <Header title={title} subtitle={subtitle} />
      <main
        // Key on pathname so navigation replays the fade-in animation.
        key={pathname}
        className="flex-1 p-6 bg-td-gray animate-page-in"
      >
        {children}
      </main>
    </div>
  );
}
