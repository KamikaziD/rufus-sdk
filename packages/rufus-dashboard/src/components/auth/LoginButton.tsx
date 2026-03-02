"use client";

import { signIn } from "next-auth/react";

export function LoginButton({ callbackUrl }: { callbackUrl: string }) {
  return (
    <button
      type="button"
      onClick={() => signIn("keycloak", { callbackUrl })}
      className="w-full bg-primary text-primary-foreground rounded-lg py-3 font-medium hover:opacity-90 transition-opacity"
    >
      Sign in with Keycloak
    </button>
  );
}
