"use client";

import { useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/hooks/use-auth";

/**
 * Blocking modal shown when a signed-in user's session expires mid-use.
 *
 * The only prior cue was a tiny (mobile-hidden) "Session Expired" label in
 * the nav — easy to miss right after generating a game, which is exactly
 * when a user needs to sign back in to save it. This dims the page and puts
 * the sign-in path front and centre.
 *
 * Mounted once globally inside AuthProvider (see app/layout.tsx). Reads the
 * shared `sessionExpired` flag, so it appears on whatever page the user is on.
 */
export function SessionExpiredModal() {
  const { sessionExpired, dismissSessionExpired } = useAuth();
  const pathname = usePathname();

  // Escape closes the modal (same as "Later") so it never traps the user.
  useEffect(() => {
    if (!sessionExpired) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") dismissSessionExpired();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [sessionExpired, dismissSessionExpired]);

  if (!sessionExpired) return null;

  // Return here after signing in so the game they just made stays in view.
  const returnUrl = encodeURIComponent(pathname || "/");
  const signInHref = `/login?returnUrl=${returnUrl}`;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="session-expired-title"
      data-testid="session-expired-modal"
      onClick={dismissSessionExpired}
    >
      <div
        className="w-full max-w-sm rounded-md bg-surface-raised brutal-card p-6 text-center"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-md bg-pop-red/20 brutal-border">
          <svg
            className="h-6 w-6 text-pop-red"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            viewBox="0 0 24 24"
            aria-hidden
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 9v3.75m0 3.75h.008M10.34 3.94l-8.19 14.2A1.5 1.5 0 003.45 20.5h17.1a1.5 1.5 0 001.3-2.36l-8.19-14.2a1.5 1.5 0 00-2.6 0z"
            />
          </svg>
        </div>

        <h2
          id="session-expired-title"
          className="font-[family-name:var(--font-heading)] text-xl font-bold tracking-tight"
        >
          You were signed out
        </h2>
        <p className="mt-2 text-sm text-txt-secondary">
          Sign in again to keep your game.
        </p>

        <div className="mt-6 flex flex-col gap-2">
          <Link
            href={signInHref}
            onClick={dismissSessionExpired}
            className="rounded-md bg-pop-yellow px-4 py-2.5 text-sm font-bold uppercase tracking-wider text-surface brutal-border transition-colors hover:bg-pop-lime cursor-pointer"
            data-testid="session-expired-sign-in"
          >
            Sign in
          </Link>
          <button
            onClick={dismissSessionExpired}
            className="rounded-md px-4 py-2 text-sm font-bold uppercase tracking-wider text-txt-muted transition-colors hover:text-txt-secondary cursor-pointer"
            data-testid="session-expired-later"
          >
            Not now
          </button>
        </div>
      </div>
    </div>
  );
}
