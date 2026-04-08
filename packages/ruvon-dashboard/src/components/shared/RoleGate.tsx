"use client";

import { useSession } from "next-auth/react";
import type { Permission } from "@/lib/roles";
import { hasPermission } from "@/lib/roles";

interface RoleGateProps {
  permission: Permission;
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

export function RoleGate({ permission, children, fallback = null }: RoleGateProps) {
  const { data: session } = useSession();
  const roles = session?.user?.roles;

  if (!hasPermission(roles, permission)) {
    return <>{fallback}</>;
  }
  return <>{children}</>;
}
