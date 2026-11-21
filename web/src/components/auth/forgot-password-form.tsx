"use client";

import { useState, useCallback } from "react";
import Link from "next/link";
import { inputClass } from "@/components/auth/auth-page";
import { requestPasswordReset } from "@/lib/auth";

export function ForgotPasswordForm() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();

      if (!email) {
        setError("Type your email.");
        return;
      }

      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        setError("That email doesn't look right.");
        return;
      }

      setIsSubmitting(true);
      setError("");

      try {
        await requestPasswordReset(email);
        setIsSuccess(true);
      } catch {
        // Still show success to prevent email enumeration
        setIsSuccess(true);
      } finally {
        setIsSubmitting(false);
      }
    },
    [email]
  );

  if (isSuccess) {
    return (
      <div className="w-full max-w-md rounded-lg bg-surface-raised brutal-card p-6">
        <h2 className="font-[family-name:var(--font-heading)] text-3xl font-bold text-center mb-4">
          Check your email
        </h2>
        <p className="text-sm font-bold text-txt-primary text-center mb-3">
          If <span className="text-pop-yellow">{email}</span> has an account,
          we sent it a link.
        </p>
        <p className="text-sm text-txt-muted text-center">
          No email? Look in your spam folder.
        </p>
        <div className="mt-6 pt-4 border-t-2 border-[var(--card-border)] text-center">
          <Link
            href="/login"
            className="text-xs font-bold uppercase tracking-wider text-pop-yellow hover:text-pop-lime transition-colors"
          >
            Back to sign in
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full max-w-md rounded-lg bg-surface-raised brutal-card p-6">
      <h2 className="font-[family-name:var(--font-heading)] text-3xl font-bold text-center mb-2">
        Forgot your password?
      </h2>
      <p className="text-sm text-txt-muted text-center mb-6">
        We&apos;ll email you a link to make a new one.
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        {error && (
          <div
            className="rounded-md border-2 border-pop-red bg-pop-red/10 p-3 text-sm font-bold text-pop-red"
            role="alert"
          >
            {error}
          </div>
        )}

        <div className="space-y-1.5">
          <label
            htmlFor="email"
            className="block text-xs font-bold uppercase tracking-wider text-txt-secondary"
          >
            Email
          </label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            disabled={isSubmitting}
            className={inputClass}
          />
        </div>

        <button
          type="submit"
          disabled={isSubmitting}
          className="w-full rounded-md bg-pop-yellow px-4 py-3 text-sm font-bold uppercase tracking-wider text-surface brutal-border transition-colors hover:bg-pop-lime cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isSubmitting ? "Sending…" : "Send link"}
        </button>
      </form>

      <div className="mt-6 pt-4 border-t-2 border-[var(--card-border)] text-center">
        <Link
          href="/login"
          className="text-xs font-bold uppercase tracking-wider text-txt-muted hover:text-pop-yellow transition-colors"
        >
          Back to sign in
        </Link>
      </div>
    </div>
  );
}
