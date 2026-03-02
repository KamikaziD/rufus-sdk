"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession } from "next-auth/react";
import { cn } from "@/lib/utils";
import { getVisibleNavItems } from "@/lib/roles";
import {
  LayoutDashboard, GitBranch, CheckSquare, Cpu, Shield,
  Clock, FileText, Settings
} from "lucide-react";

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  LayoutDashboard, GitBranch, CheckSquare, Cpu, Shield,
  Clock, FileText, Settings,
};

export function Sidebar() {
  const pathname = usePathname();
  const { data: session } = useSession();
  const roles = session?.user?.roles ?? [];
  const navItems = getVisibleNavItems(roles as string[]);

  return (
    <aside className="fixed inset-y-0 left-0 z-50 flex w-56 flex-col border-r bg-background">
      {/* Brand */}
      <div className="flex h-14 items-center gap-2 border-b px-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
          <span className="text-sm font-bold text-primary-foreground">R</span>
        </div>
        <span className="font-semibold text-sm">Rufus Edge</span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-4">
        <ul className="space-y-1 px-2">
          {navItems.map((item) => {
            const Icon = ICON_MAP[item.icon];
            const isActive = item.href === "/"
              ? pathname === "/"
              : pathname.startsWith(item.href);

            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={cn(
                    "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                  )}
                >
                  {Icon && <Icon className="h-4 w-4" />}
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* User info */}
      <div className="border-t p-3">
        <div className="flex items-center gap-2 rounded-md px-2 py-1.5">
          <div className="h-7 w-7 rounded-full bg-muted flex items-center justify-center">
            <span className="text-xs font-medium">
              {session?.user?.name?.charAt(0) ?? "?"}
            </span>
          </div>
          <div className="flex-1 overflow-hidden">
            <p className="truncate text-xs font-medium">{session?.user?.name}</p>
            <p className="truncate text-xs text-muted-foreground">
              {roles[0] ?? ""}
            </p>
          </div>
        </div>
      </div>
    </aside>
  );
}
