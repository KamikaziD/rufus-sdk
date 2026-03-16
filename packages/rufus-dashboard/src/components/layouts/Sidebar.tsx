"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession } from "next-auth/react";
import { cn } from "@/lib/utils";
import { getVisibleNavItems } from "@/lib/roles";
import {
  LayoutDashboard, GitBranch, CheckSquare, Cpu, Shield,
  Clock, FileText, Settings, Server
} from "lucide-react";

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  LayoutDashboard, GitBranch, CheckSquare, Cpu, Shield,
  Clock, FileText, Settings, Server,
};

// Section groupings — icons as anchors
const SECTION_LABELS: Record<string, string> = {
  LayoutDashboard: "EXECUTION",
  GitBranch:       "EXECUTION",
  CheckSquare:     "EXECUTION",
  Cpu:             "FLEET",
  Server:          "FLEET",
  Shield:          "SYSTEM",
  Clock:           "SYSTEM",
  FileText:        "SYSTEM",
  Settings:        "SYSTEM",
};

export function Sidebar() {
  const pathname = usePathname();
  const { data: session } = useSession();
  const roles = session?.user?.roles ?? [];
  const navItems = getVisibleNavItems(roles as string[]);

  // Inject section labels
  let lastSection = "";
  const renderedItems: React.ReactNode[] = [];

  navItems.forEach((item) => {
    const section = SECTION_LABELS[item.icon] ?? "";
    if (section && section !== lastSection) {
      lastSection = section;
      renderedItems.push(
        <li key={`section-${section}`} className="mt-4 mb-1 px-3">
          <span className="text-[9px] font-mono tracking-widest text-zinc-600 uppercase">{section}</span>
        </li>
      );
    }

    const Icon = ICON_MAP[item.icon];
    const isActive = item.href === "/"
      ? pathname === "/"
      : pathname.startsWith(item.href);

    renderedItems.push(
      <li key={item.href}>
        <Link
          href={item.href}
          className={cn(
            "flex items-center gap-3 px-3 py-2 text-sm font-medium transition-colors rounded-none",
            isActive
              ? "bg-amber-500/10 text-amber-400 border-l-2 border-amber-500"
              : "text-zinc-500 hover:text-zinc-200 hover:bg-[#1E1E22] border-l-2 border-transparent"
          )}
        >
          {Icon && <Icon className="h-4 w-4 flex-shrink-0" />}
          {item.label}
        </Link>
      </li>
    );
  });

  return (
    <aside className="fixed inset-y-0 left-0 z-50 flex w-56 flex-col border-r border-[#1E1E22] bg-[#0A0A0B]">
      {/* Brand */}
      <div className="flex h-14 items-center gap-2 border-b border-[#1E1E22] px-4">
        <span className="font-mono text-sm font-semibold">
          <span className="text-amber-400">RUFUS</span>
          <span className="text-zinc-500"> EDGE</span>
        </span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-2">
        <ul className="space-y-0.5 px-2">
          {renderedItems}
        </ul>
      </nav>

      {/* User chip */}
      <div className="border-t border-[#1E1E22] p-3">
        <div className="px-2 py-1.5">
          <p className="font-mono text-xs text-zinc-500 truncate">{session?.user?.name ?? "—"}</p>
          <p className="font-mono text-[10px] text-zinc-600 truncate uppercase tracking-wider mt-0.5">
            {(roles[0] as string) ?? ""}
          </p>
        </div>
      </div>
    </aside>
  );
}
