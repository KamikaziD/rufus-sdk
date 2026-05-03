/**
 * Rufus Dashboard — Playwright smoke tests
 *
 * Auth strategy:
 *  - Middleware bypass is enabled via PLAYWRIGHT_TEST_BYPASS=true (set in playwright.config.ts webServer env).
 *  - Tests that need auth set `X-Test-Roles` header via page.setExtraHTTPHeaders().
 *  - The /api/auth/session and Rufus API endpoints are mocked via page.route() so
 *    client-side hooks get valid data without a running backend.
 */

import { test, expect, type Page } from "@playwright/test";

// ── Shared session mock ───────────────────────────────────────────────────────

const SUPER_ADMIN_SESSION = {
  user: {
    name: "Test Admin",
    email: "admin@test.local",
    image: null,
    roles: ["SUPER_ADMIN"],
  },
  expires: new Date(Date.now() + 3600_000).toISOString(),
  accessToken: "fake-test-token",
};

const OPERATOR_SESSION = {
  user: {
    name: "Test Operator",
    email: "operator@test.local",
    image: null,
    roles: ["WORKFLOW_OPERATOR"],
  },
  expires: new Date(Date.now() + 3600_000).toISOString(),
  accessToken: "fake-test-token",
};

const READ_ONLY_SESSION = {
  user: {
    name: "Test ReadOnly",
    email: "readonly@test.local",
    image: null,
    roles: ["READ_ONLY"],
  },
  expires: new Date(Date.now() + 3600_000).toISOString(),
  accessToken: "fake-test-token",
};

async function mockSession(page: Page, session: Record<string, unknown>) {
  await page.route("**/api/auth/session", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(session),
    })
  );
}

async function mockEmptyApis(page: Page) {
  // Mock all Rufus API calls to return graceful empty responses
  await page.route("**/api/v1/**", (route) => {
    const url = route.request().url();
    // Default empty shapes for each data type
    if (url.includes("/workflows/executions")) {
      return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    }
    if (url.includes("/workflows") && !url.includes("workflow/")) {
      return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    }
    if (url.includes("/devices")) {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ devices: [], total: 0 }) });
    }
    if (url.includes("/metrics")) {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
    }
    if (url.includes("/admin/workers")) {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ workers: [] }) });
    }
    if (url.includes("/policies")) {
      return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    }
    if (url.includes("/schedules")) {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ schedules: [], count: 0 }) });
    }
    if (url.includes("/approvals") || url.includes("/hitl")) {
      return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    }
    if (url.includes("/audit")) {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ entries: [], total_count: 0 }) });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: "null" });
  });
}

// ── Test 1: Unauthenticated redirect ─────────────────────────────────────────

test("unauthenticated / redirects to /login", async ({ page }) => {
  // No test headers → middleware treats as unauthenticated → redirects to /login
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
});

// ── Test 2: Login page renders ────────────────────────────────────────────────

test("login page renders sign-in button", async ({ page }) => {
  await page.goto("/login");
  // The login page should show a button to sign in with Keycloak
  const signInBtn = page.getByRole("button", { name: /sign in/i });
  await expect(signInBtn).toBeVisible();
});

// ── Test 3: Overview page (mocked SUPER_ADMIN session) ───────────────────────

test("overview page shows KPI cards for SUPER_ADMIN", async ({ page }) => {
  await page.setExtraHTTPHeaders({ "x-test-bypass": "true", "x-test-roles": "SUPER_ADMIN" });
  await mockSession(page, SUPER_ADMIN_SESSION);
  await mockEmptyApis(page);

  await page.goto("/");
  // Overview should show KPI card headings
  await expect(page.getByText("Active Workflows")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("Online Devices")).toBeVisible({ timeout: 10_000 });
});

// ── Test 4: Workflows page ────────────────────────────────────────────────────

test("workflows page shows table for SUPER_ADMIN", async ({ page }) => {
  await page.setExtraHTTPHeaders({ "x-test-bypass": "true", "x-test-roles": "SUPER_ADMIN" });
  await mockSession(page, SUPER_ADMIN_SESSION);
  await mockEmptyApis(page);

  await page.goto("/workflows");
  // Should show the Workflows heading — no crash
  await expect(page.getByRole("heading", { name: "Workflows" })).toBeVisible({ timeout: 10_000 });
  // No unhandled error dialog
  await expect(page.locator("h1")).not.toBeEmpty();
});

// ── Test 5: Devices page ──────────────────────────────────────────────────────

test("devices page shows 'Register Device' button for FLEET_MANAGER", async ({ page }) => {
  await page.setExtraHTTPHeaders({ "x-test-bypass": "true", "x-test-roles": "SUPER_ADMIN,FLEET_MANAGER" });
  await mockSession(page, SUPER_ADMIN_SESSION);
  await mockEmptyApis(page);

  await page.goto("/devices");
  await expect(page.getByRole("button", { name: /register device/i })).toBeVisible({ timeout: 10_000 });
});

// ── Test 6: Approvals page ────────────────────────────────────────────────────

test("approvals page renders without crash for WORKFLOW_OPERATOR", async ({ page }) => {
  await page.setExtraHTTPHeaders({ "x-test-bypass": "true", "x-test-roles": "WORKFLOW_OPERATOR" });
  await mockSession(page, OPERATOR_SESSION);
  await mockEmptyApis(page);

  // Mock the HITL/approvals specific endpoint
  await page.route("**/api/v1/workflow/*/status", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ workflows: [] }) })
  );

  await page.goto("/approvals");
  // Page heading should be visible (no crash/error boundary); actual heading is "Approval Queue"
  await expect(page.getByRole("heading", { name: /approval queue/i })).toBeVisible({ timeout: 10_000 });
});

// ── Test 7: Admin page RBAC — READ_ONLY forbidden ────────────────────────────

test("admin page redirects READ_ONLY user to /?error=forbidden", async ({ page }) => {
  // READ_ONLY role → middleware should redirect away from /admin
  await page.setExtraHTTPHeaders({ "x-test-bypass": "true", "x-test-roles": "READ_ONLY" });
  await mockSession(page, READ_ONLY_SESSION);
  await mockEmptyApis(page);

  await page.goto("/admin");
  // Should NOT stay on /admin
  await expect(page).not.toHaveURL(/\/admin/, { timeout: 5_000 });
});

// ── Test 8: New Workflow page form renders ────────────────────────────────────

test("new workflow page shows form for WORKFLOW_OPERATOR", async ({ page }) => {
  await page.setExtraHTTPHeaders({ "x-test-bypass": "true", "x-test-roles": "WORKFLOW_OPERATOR" });
  await mockSession(page, OPERATOR_SESSION);
  await mockEmptyApis(page);

  await page.goto("/workflows/new");
  // Actual heading is "Start Workflow"
  await expect(page.getByRole("heading", { name: /start workflow/i })).toBeVisible({ timeout: 10_000 });
  // Form should render — button text is "Start Workflow" (initially disabled, but visible)
  await expect(page.getByRole("button", { name: /start workflow/i })).toBeVisible({ timeout: 10_000 });
});
