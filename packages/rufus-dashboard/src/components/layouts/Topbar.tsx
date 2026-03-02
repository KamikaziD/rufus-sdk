"use client";

import { signOut } from "next-auth/react";
import { useSession } from "next-auth/react";
import { Button } from "@/components/ui/button";
import { LogOut, Bell } from "lucide-react";

export function Topbar() {
  const { data: session } = useSession();

  return (
    <header className="fixed top-0 right-0 z-40 flex h-14 items-center gap-4 border-b bg-background px-6 left-56">
      <div className="flex-1" />

      <Button variant="ghost" size="icon" aria-label="Notifications">
        <Bell className="h-4 w-4" />
      </Button>

      <div className="flex items-center gap-2">
        <span className="text-sm text-muted-foreground hidden sm:block">
          {session?.user?.email}
        </span>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => signOut({ callbackUrl: "/login" })}
          aria-label="Sign out"
        >
          <LogOut className="h-4 w-4" />
        </Button>
      </div>
    </header>
  );
}
