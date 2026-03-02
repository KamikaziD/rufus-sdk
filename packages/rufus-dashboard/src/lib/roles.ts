import type { RufusRole } from "@/types";

/** Complete RBAC permission matrix */
export const PERMISSIONS = {
  // Workflow actions
  startWorkflow:       ["SUPER_ADMIN", "WORKFLOW_OPERATOR"] as RufusRole[],
  resumeWorkflow:      ["SUPER_ADMIN", "WORKFLOW_OPERATOR"] as RufusRole[],
  cancelWorkflow:      ["SUPER_ADMIN", "WORKFLOW_OPERATOR"] as RufusRole[],
  retryWorkflow:       ["SUPER_ADMIN", "WORKFLOW_OPERATOR"] as RufusRole[],
  viewWorkflow:        ["SUPER_ADMIN", "WORKFLOW_OPERATOR", "AUDITOR", "READ_ONLY"] as RufusRole[],
  debugWorkflow:       ["SUPER_ADMIN", "WORKFLOW_OPERATOR"] as RufusRole[],
  approveHitl:         ["SUPER_ADMIN", "WORKFLOW_OPERATOR"] as RufusRole[],

  // Device actions
  registerDevice:      ["SUPER_ADMIN", "FLEET_MANAGER"] as RufusRole[],
  deleteDevice:        ["SUPER_ADMIN", "FLEET_MANAGER"] as RufusRole[],
  sendCommand:         ["SUPER_ADMIN", "FLEET_MANAGER"] as RufusRole[],
  viewDevices:         ["SUPER_ADMIN", "FLEET_MANAGER", "WORKFLOW_OPERATOR", "AUDITOR", "READ_ONLY"] as RufusRole[],
  configPush:          ["SUPER_ADMIN", "FLEET_MANAGER"] as RufusRole[],

  // Audit
  viewAudit:           ["SUPER_ADMIN", "AUDITOR"] as RufusRole[],
  exportAudit:         ["SUPER_ADMIN", "AUDITOR"] as RufusRole[],

  // Policies
  managePolicies:      ["SUPER_ADMIN"] as RufusRole[],
  viewPolicies:        ["SUPER_ADMIN", "FLEET_MANAGER", "AUDITOR"] as RufusRole[],

  // Admin
  adminPanel:          ["SUPER_ADMIN"] as RufusRole[],
  viewSchedules:       ["SUPER_ADMIN", "WORKFLOW_OPERATOR"] as RufusRole[],
  manageSchedules:     ["SUPER_ADMIN", "WORKFLOW_OPERATOR"] as RufusRole[],
} as const;

export type Permission = keyof typeof PERMISSIONS;

/**
 * Check if a user (by roles) has a specific permission.
 */
export function hasPermission(
  userRoles: string[] | undefined,
  permission: Permission
): boolean {
  if (!userRoles || userRoles.length === 0) return false;
  const allowed = PERMISSIONS[permission] as readonly string[];
  return userRoles.some((r) => allowed.includes(r));
}

/**
 * Check if a user has any of the given roles.
 */
export function hasRole(userRoles: string[] | undefined, ...roles: RufusRole[]): boolean {
  if (!userRoles) return false;
  return userRoles.some((r) => roles.includes(r as RufusRole));
}

/** Nav items visible per role */
export function getVisibleNavItems(userRoles: string[] | undefined): NavItem[] {
  return NAV_ITEMS.filter((item) =>
    !item.requiredRoles || item.requiredRoles.some((r) => userRoles?.includes(r))
  );
}

export interface NavItem {
  label: string;
  href: string;
  icon: string;
  requiredRoles?: RufusRole[];
}

export const NAV_ITEMS: NavItem[] = [
  { label: "Overview",   href: "/",            icon: "LayoutDashboard" },
  { label: "Workflows",  href: "/workflows",   icon: "GitBranch",        requiredRoles: ["SUPER_ADMIN", "WORKFLOW_OPERATOR", "AUDITOR", "READ_ONLY"] },
  { label: "Approvals",  href: "/approvals",   icon: "CheckSquare",      requiredRoles: ["SUPER_ADMIN", "WORKFLOW_OPERATOR"] },
  { label: "Devices",    href: "/devices",     icon: "Cpu",              requiredRoles: ["SUPER_ADMIN", "FLEET_MANAGER", "WORKFLOW_OPERATOR", "AUDITOR", "READ_ONLY"] },
  { label: "Policies",   href: "/policies",    icon: "Shield",           requiredRoles: ["SUPER_ADMIN", "FLEET_MANAGER", "AUDITOR"] },
  { label: "Schedules",  href: "/schedules",   icon: "Clock",            requiredRoles: ["SUPER_ADMIN", "WORKFLOW_OPERATOR"] },
  { label: "Audit",      href: "/audit",       icon: "FileText",         requiredRoles: ["SUPER_ADMIN", "AUDITOR"] },
  { label: "Admin",      href: "/admin",       icon: "Settings",         requiredRoles: ["SUPER_ADMIN"] },
];
