import NextAuth from "next-auth";
import type { JWT } from "next-auth/jwt";

interface ExtendedToken extends JWT {
  accessToken?: string;
  refreshToken?: string;
  accessTokenExpires?: number;
  roles?: string[];
  error?: string;
}

// Server-side Keycloak URL (Docker internal network, never reaches the browser)
const KC_INTERNAL = "http://keycloak:8080/realms/ruvon";

// Public-facing Keycloak URL (browser follows redirects to this host)
const KC_PUBLIC = process.env.KEYCLOAK_ISSUER!; // http://localhost:8080/realms/rufus

export const { handlers, auth, signIn, signOut } = NextAuth({
  basePath: "/api/auth",
  trustHost: true,
  providers: [
    {
      id: "keycloak",
      name: "Keycloak",
      // Use type "oauth" to skip OIDC auto-discovery from the issuer URL.
      // This lets us point server-side token/userinfo calls at the Docker-internal
      // hostname (keycloak:8080) while the browser-facing auth redirect uses localhost.
      type: "oauth",
      clientId: process.env.KEYCLOAK_CLIENT_ID!,
      issuer: KC_PUBLIC,
      authorization: {
        url: `${KC_PUBLIC}/protocol/openid-connect/auth`,
        params: { scope: "openid email profile", response_type: "code" },
      },
      token: `${KC_INTERNAL}/protocol/openid-connect/token`,
      // oauth4webapi's userInfoRequest() enforces HTTPS even in dev, so we
      // bypass it with a custom request function that uses plain fetch.
      userinfo: {
        url: `${KC_INTERNAL}/protocol/openid-connect/userinfo`,
        async request({ tokens }: { tokens: { access_token?: string } }) {
          const res = await fetch(
            `${KC_INTERNAL}/protocol/openid-connect/userinfo`,
            { headers: { Authorization: `Bearer ${tokens.access_token}` } }
          );
          return res.json();
        },
      },
      checks: ["pkce", "state"],
      profile(profile: Record<string, unknown>) {
        const given = (profile.given_name as string) ?? "";
        const family = (profile.family_name as string) ?? "";
        return {
          id: profile.sub as string,
          name: [given, family].filter(Boolean).join(" ") || (profile.preferred_username as string) || (profile.sub as string),
          email: (profile.email as string) ?? null,
          image: null,
        };
      },
    },
  ],
  callbacks: {
    async authorized({ request }: { auth: unknown; request: Request }) {
      // Playwright test bypass — only active when PLAYWRIGHT_TEST_BYPASS=true (test webServer only)
      if (process.env.PLAYWRIGHT_TEST_BYPASS === "true") {
        const testBypass = request.headers.get("x-test-bypass");
        if (testBypass === "true") return true;
      }
      // Normal flow: session presence is checked by the middleware handler below
      return true; // let middleware.ts handle auth redirects
    },
    async jwt({ token, account }) {
      const ext = token as ExtendedToken;
      if (account) {
        ext.accessToken = account.access_token;
        ext.refreshToken = account.refresh_token;
        ext.accessTokenExpires = account.expires_at
          ? account.expires_at * 1000
          : undefined;
        try {
          if (account.access_token) {
            const payload = JSON.parse(
              Buffer.from(account.access_token.split(".")[1], "base64url").toString()
            );
            ext.roles = payload?.realm_access?.roles ?? [];
          }
        } catch {
          ext.roles = [];
        }
      }
      return ext;
    },
    async session({ session, token }) {
      const ext = token as ExtendedToken;
      (session as unknown as Record<string, unknown>).accessToken = ext.accessToken;
      session.user.roles = (ext.roles ?? []) as string[];
      return session;
    },
  },
  pages: {
    signIn: "/login",
  },
});

declare module "next-auth" {
  interface Session {
    accessToken?: string;
    user: {
      name?: string | null;
      email?: string | null;
      image?: string | null;
      roles?: string[];
    };
  }
}
