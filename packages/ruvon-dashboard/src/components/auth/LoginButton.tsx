"use client";

import { signIn } from "next-auth/react";

export function LoginButton({ callbackUrl }: { callbackUrl: string }) {
  return (
    <button
      type="button"
      onClick={() => signIn("keycloak", { callbackUrl })}
      className="w-full bg-amber-500 hover:bg-amber-600 text-black font-mono text-sm rounded-none py-3 transition-colors"
    >
      Sign in with Keycloak
    </button>
  );
}
