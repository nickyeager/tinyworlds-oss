"use client";

import { useState, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { inputClass } from "@/components/auth/auth-page";
import { useAuth } from "@/hooks/use-auth";

interface FormErrors {
  email?: string;
  password?: string;
  general?: string;
}

export function LoginForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<FormErrors>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { login } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const returnUrl = searchParams.get("returnUrl") || "/";

  const validate = useCallback((): boolean => {
    const newErrors: FormErrors = {};

    if (!email) {
      newErrors.email = "Type your email.";
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      newErrors.email = "That email doesn't look right.";
    }

    if (!password) {
      newErrors.password = "Type your password.";
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }, [email, password]);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();

      if (!validate()) return;

      setIsSubmitting(true);
      setErrors({});

      try {
        await login(email, password);
        router.push(decodeURIComponent(returnUrl));
      } catch (err) {
        setErrors({
          general:
            err instanceof Error ? err.message : "Couldn't sign in. Try again.",
        });
      } finally {
        setIsSubmitting(false);
      }
    },
    [email, password, login, router, returnUrl, validate]
  );

  return (
    <div className="w-full max-w-md rounded-lg bg-surface-raised brutal-card p-6">
      <h2 className="font-[family-name:var(--font-heading)] text-3xl font-bold text-center mb-6">
        Sign in
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
            aria-invalid={!!errors.email}
            disabled={isSubmitting}
            className={inputClass}
          />
          {errors.email && (
            <p className="text-xs font-bold text-pop-red">{errors.email}</p>
          )}
        </div>

        <div className="space-y-1.5">
          <label
            htmlFor="password"
            className="block text-xs font-bold uppercase tracking-wider text-txt-secondary"
          >
            Password
          </label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={!!errors.password}
            disabled={isSubmitting}
            className={inputClass}
          />
          {errors.password && (
            <p className="text-xs font-bold text-pop-red">{errors.password}</p>
          )}
        </div>

        <div className="flex justify-end">
          <Link
            href="/forgot-password"
            className="text-xs font-bold uppercase tracking-wider text-txt-secondary hover:text-pop-yellow transition-colors"
          >
            Forgot password?
          </Link>
        </div>

        <button
          type="submit"
          disabled={isSubmitting}
          className="w-full rounded-md bg-pop-yellow px-4 py-3 text-sm font-bold uppercase tracking-wider text-surface brutal-border transition-colors hover:bg-pop-lime cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isSubmitting ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <div className="mt-6 pt-4 border-t-2 border-[var(--card-border)] text-center">
        <p className="text-xs font-bold uppercase tracking-wider text-txt-muted">
          New here?{" "}
          <Link
            href="/register"
            className="text-pop-yellow hover:text-pop-lime transition-colors"
          >
            Sign up
          </Link>
        </p>
      </div>
    </div>
  );
}
