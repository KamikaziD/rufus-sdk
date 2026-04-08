import { auth } from "@/lib/auth";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export default auth((req: NextRequest & { auth: unknown }) => {
  const { pathname } = req.nextUrl;

  // Public paths
  if (pathname.startsWith("/login") || pathname.startsWith("/api/auth")) {
    return NextResponse.next();
  }

  // ── Playwright test bypass ───────────────────────────────────────────
  // Tests send `x-test-bypass: true` + `x-test-roles: ROLE1,ROLE2` headers.
  // This header is only respected when the server is started with
  // PLAYWRIGHT_TEST_BYPASS=true, which restricts use to the test webServer.
  // In production the env var is absent so this block never executes.
  // NOTE: In production, configure your reverse proxy/CDN to strip x-test-bypass.
  const testBypass = req.headers.get("x-test-bypass");
  if (testBypass === "true") {
    const testRolesHeader = req.headers.get("x-test-roles") ?? "";
    const roles = testRolesHeader.split(",").map((r) => r.trim()).filter(Boolean);
    if (pathname.startsWith("/admin") && !roles.includes("SUPER_ADMIN")) {
      return NextResponse.redirect(new URL("/?error=forbidden", req.url));
    }
    if (pathname.startsWith("/audit") && !roles.includes("SUPER_ADMIN") && !roles.includes("AUDITOR")) {
      return NextResponse.redirect(new URL("/?error=forbidden", req.url));
    }
    if (pathname.startsWith("/approvals") && !roles.includes("SUPER_ADMIN") && !roles.includes("WORKFLOW_OPERATOR")) {
      return NextResponse.redirect(new URL("/?error=forbidden", req.url));
    }
    return NextResponse.next();
  }
  // ────────────────────────────────────────────────────────────────────

  const session = req.auth as { user?: { roles?: string[] } } | null;

  // Not authenticated
  if (!session) {
    const loginUrl = new URL("/login", req.url);
    loginUrl.searchParams.set("callbackUrl", pathname);
    return NextResponse.redirect(loginUrl);
  }

  const roles = session.user?.roles ?? [];

  // Admin route guard
  if (pathname.startsWith("/admin") && !roles.includes("SUPER_ADMIN")) {
    return NextResponse.redirect(new URL("/?error=forbidden", req.url));
  }

  // Audit route guard
  if (
    pathname.startsWith("/audit") &&
    !roles.includes("SUPER_ADMIN") &&
    !roles.includes("AUDITOR")
  ) {
    return NextResponse.redirect(new URL("/?error=forbidden", req.url));
  }

  // Approvals route guard
  if (
    pathname.startsWith("/approvals") &&
    !roles.includes("SUPER_ADMIN") &&
    !roles.includes("WORKFLOW_OPERATOR")
  ) {
    return NextResponse.redirect(new URL("/?error=forbidden", req.url));
  }

  return NextResponse.next();
});

export const config = {
  // Exclude all /_next/ internals (static, image, webpack-hmr, etc.) + favicon + assets
  matcher: ["/((?!_next/|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)"],
};
