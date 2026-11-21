"use client";

import { useState, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { inputClass } from "@/components/auth/auth-page";
import { resetPassword } from "@/lib/auth";

interface FormErrors {
  password?: string;
  confirmPassword?: string;
  general?: string;
}

export function ResetPasswordForm() {
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [errors, setErrors] = useState<FormErrors>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);

  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  const validate = useCallback((): boolean => {
    const newErrors: FormErrors = {};

    if (!password) {
      newErrors.password = "Pick a password.";
    } else if (password.length < 8) {
      newErrors.password = "Use at least 8 characters.";
    }

    if (password !== confirmPassword) {
      newErrors.confirmPassword = "The passwords don't match.";
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }, [password, confirmPassword]);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();

      if (!token || !validate()) return;

      setIsSubmitting(true);
      setErrors({});

      try {
        await resetPassword(token, password);
        setIsSuccess(true);
        setTimeout(() => {
          router.push("/login");
        }, 2000);
      } catch (err) {
        setErrors({
          general:
            err instanceof Error
              ? err.message
              : "Couldn't change your password. Get a new link and try again.",
        });
      } finally {
        setIsSubmitting(false);
      }
    },
    [token, password, validate, router]
  );

  if (!token) {
    return (
      <div className="w-full max-w-md rounded-lg bg-surface-raised brutal-card p-6 text-center">
        <h2 className="font-[family-name:var(--font-heading)] text-3xl font-bold mb-4">
          This link doesn&apos;t work
        </h2>
        <p className="text-sm font-bold text-txt-primary mb-6">
          It may be too old.
        </p>
        <Link
          href="/forgot-password"
          className="inline-block w-full rounded-md bg-pop-yellow px-4 py-3 text-sm font-bold uppercase tracking-wider text-surface brutal-border transition-colors hover:bg-pop-lime"
        >
          Get a new link
        </Link>
      </div>
    );
  }

  if (isSuccess) {
    return (
      <div className="w-full max-w-md rounded-lg bg-surface-raised brutal-card p-6 text-center">
        <h2 className="font-[family-name:var(--font-heading)] text-3xl font-bold mb-4">
          Password changed
        </h2>
        <p className="text-sm font-bold text-txt-primary">
          Taking you to sign in…
        </p>
      </div>
    );
  }

  return (
    <div className="w-full max-w-md rounded-lg bg-surface-raised brutal-card p-6">
      <h2 className="font-[family-name:var(--font-heading)] text-3xl font-bold text-center mb-6">
        Make a new password
      </h2>

      <form onSubmit={handleSubmit} className="space-y-4">
        {errors.general && (
          <div
            className="rounded-md border-2 border-pop-red bg-pop-red/10 p-3 text-sm font-bold text-pop-red"
            role="alert"
          >
            {errors.general}
          </div>
        )}

        <div className="space-y-1.5">
          <label
            htmlFor="password"
            className="block text-xs font-bold uppercase tracking-wider text-txt-secondary"
          >
            New password
          </label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="At least 8 characters"
            aria-invalid={!!errors.password}
            disabled={isSubmitting}
            className={inputClass}
          />
          {errors.password && (
            <p className="text-xs font-bold text-pop-red">{errors.password}</p>
          )}
        </div>

        <div className="space-y-1.5">
          <label
            htmlFor="confirmPassword"
            className="block text-xs font-bold uppercase tracking-wider text-txt-secondary"
          >
            Password again
          </label>
          <input
            id="confirmPassword"
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            aria-invalid={!!errors.confirmPassword}
            disabled={isSubmitting}
            className={inputClass}
          />
          {errors.confirmPassword && (
            <p className="text-xs font-bold text-pop-red">{errors.confirmPassword}</p>
          )}
        </div>

        <button
          type="submit"
          disabled={isSubmitting}
          className="w-full rounded-md bg-pop-yellow px-4 py-3 text-sm font-bold uppercase tracking-wider text-surface brutal-border transition-colors hover:bg-pop-lime cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isSubmitting ? "Saving…" : "Save password"}
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
