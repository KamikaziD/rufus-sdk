import { defineConfig, devices } from "@playwright/test";

// Use a dedicated port so tests never accidentally reuse a dev server
// that lacks the PLAYWRIGHT_TEST_BYPASS env var.
const TEST_PORT = 3099;
const BASE_URL = `http://localhost:${TEST_PORT}`;

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  retries: 0,
  reporter: "list",

  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  webServer: {
    command: `PORT=${TEST_PORT} npm run dev`,
    url: BASE_URL,
    // Always start a fresh server so the bypass env vars are guaranteed to be active
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      PORT: String(TEST_PORT),
      NEXTAUTH_SECRET: "playwright-test-secret-32-chars-ok",
      NEXTAUTH_URL: BASE_URL,
      PLAYWRIGHT_TEST_BYPASS: "true",
      // Dummy Keycloak values — auth is bypassed in tests
      KEYCLOAK_ISSUER: "http://localhost:8080/realms/rufus",
      KEYCLOAK_CLIENT_ID: "rufus-dashboard",
      NEXT_PUBLIC_RUFUS_API_URL: "http://localhost:8000",
    },
  },
});
