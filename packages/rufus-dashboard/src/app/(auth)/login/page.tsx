import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { LoginButton } from "@/components/auth/LoginButton";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ callbackUrl?: string; error?: string }>;
}) {
  const session = await auth();
  const params = await searchParams;

  if (session) {
    redirect(params.callbackUrl ?? "/");
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-900 to-slate-800">
      <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl p-10 w-full max-w-sm flex flex-col items-center gap-6">
        {/* Logo */}
        <div className="flex flex-col items-center gap-2">
          <div className="w-14 h-14 bg-primary rounded-2xl flex items-center justify-center">
            <span className="text-primary-foreground font-bold text-2xl">R</span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight">Rufus Edge</h1>
          <p className="text-muted-foreground text-sm text-center">
            Cloud Control Plane Dashboard
          </p>
        </div>

        {params.error && (
          <div className="w-full bg-destructive/10 text-destructive text-sm px-4 py-2 rounded-lg">
            {params.error === "forbidden"
              ? "You do not have permission to access that page."
              : "Authentication failed. Please try again."}
          </div>
        )}

        <LoginButton callbackUrl={params.callbackUrl ?? "/"} />

        <p className="text-xs text-muted-foreground text-center">
          Secured by Keycloak OIDC
        </p>
      </div>
    </div>
  );
}
