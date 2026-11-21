import { Suspense, type ReactNode } from "react";
import Link from "next/link";

export const inputClass =
  "w-full rounded-md bg-surface-raised px-3 py-2.5 text-sm font-bold text-txt-primary placeholder:font-normal placeholder:text-txt-muted brutal-border focus:outline-none focus:border-pop-yellow disabled:opacity-50 transition-colors";

/** Shared frame for the sign-in, sign-up and password pages. */
export function AuthPage({ children }: { children: ReactNode }) {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center bg-surface text-txt-primary selection:bg-pop-yellow/30 px-4 py-8">
      <Link
        href="/create"
        className="mb-8 flex items-center gap-3 transition-opacity hover:opacity-80"
      >
        <div className="flex h-11 w-11 items-center justify-center rounded-md bg-pop-yellow brutal-border brutal-shadow">
          <svg
            className="h-6 w-6 text-surface"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            viewBox="0 0 24 24"
          >
            <path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z" />
          </svg>
        </div>
        <span className="font-[family-name:var(--font-heading)] text-3xl font-bold tracking-tight">
          TinyWorlds
        </span>
      </Link>

      {/* The forms read the URL, which needs a Suspense boundary. */}
      <Suspense fallback={null}>{children}</Suspense>
    </main>
  );
}
