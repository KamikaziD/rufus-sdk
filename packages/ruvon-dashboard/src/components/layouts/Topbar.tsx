"use client";

import { signOut } from "next-auth/react";
import { useSession } from "next-auth/react";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { LogOut } from "lucide-react";

function useClock() {
  const [time, setTime] = useState("");
  useEffect(() => {
    function tick() {
      const now = new Date();
      setTime(now.toLocaleTimeString("en-GB", { hour12: false }));
    }
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  return time;
}

function pageTitle(pathname: string): string {
  const segments = pathname.split("/").filter(Boolean);
  if (!segments.length) return "OVERVIEW";
  return segments[segments.length - 1].toUpperCase().replace(/-/g, " ");
}

export function Topbar() {
  const { data: session } = useSession();
  const pathname = usePathname();
  const clock = useClock();

  return (
    <header className="fixed top-0 right-0 z-40 flex h-14 items-center gap-4 border-b border-[#1E1E22] bg-[#0D0D0F] px-6 left-56">
      <span className="font-mono text-xs text-zinc-500 tracking-widest uppercase">
        {pageTitle(pathname)}
      </span>

      <div className="flex-1" />

      <span className="font-mono text-xs text-zinc-600 tabular-nums">{clock}</span>

      <span className="text-zinc-700 text-xs">|</span>

      <button
        onClick={() => signOut({ callbackUrl: "/login" })}
        aria-label="Sign out"
        className="flex items-center gap-1.5 font-mono text-xs text-zinc-500 hover:text-zinc-200 transition-colors"
      >
        <LogOut className="h-3.5 w-3.5" />
        {session?.user?.email && (
          <span className="hidden sm:block">{session.user.email}</span>
        )}
      </button>
    </header>
  );
}
