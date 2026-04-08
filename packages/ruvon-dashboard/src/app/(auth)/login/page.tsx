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
    <div
      className="min-h-screen flex items-center justify-center bg-[#0A0A0B]"
      style={{
        backgroundImage:
          "linear-gradient(rgba(30,30,34,.6) 1px, transparent 1px), linear-gradient(90deg, rgba(30,30,34,.6) 1px, transparent 1px)",
        backgroundSize: "40px 40px",
      }}
    >
      <div className="bg-[#111113] border border-[#1E1E22] rounded-none w-80 p-8 flex flex-col gap-6">
        {/* Logo */}
        <div className="text-center">
          <div className="font-mono text-base font-semibold">
            <span className="text-amber-400">RUFUS EDGE</span>
            <span className="text-zinc-600"> · </span>
            <span className="text-zinc-500">CONTROL PLANE</span>
          </div>
          <p className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest mt-2">
            Secured by Keycloak OIDC
          </p>
        </div>

        {params.error && (
          <div className="border-l-4 border-red-500 bg-red-500/5 font-mono text-xs text-red-400 px-3 py-2">
            {params.error === "forbidden"
              ? "You do not have permission to access that page."
              : "Authentication failed. Please try again."}
          </div>
        )}

        <LoginButton callbackUrl={params.callbackUrl ?? "/"} />
      </div>
    </div>
  );
}
