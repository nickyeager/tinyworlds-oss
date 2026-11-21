"use client";

import { useState, useCallback, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { inputClass } from "@/components/auth/auth-page";
import { useAuth } from "@/hooks/use-auth";
import { lookupInvitation } from "@/lib/auth";

interface FormErrors {
  email?: string;
  username?: string;
  password?: string;
  confirmPassword?: string;
  general?: string;
}

export function RegisterForm() {
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [errors, setErrors] = useState<FormErrors>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { register, isAnonymous, upgradeAccount } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const isUpgrade = searchParams.get("upgrade") === "true";
  const returnUrl = searchParams.get("returnUrl") || "/";
  const inviteToken = searchParams.get("invite");

  const [inviteStatus, setInviteStatus] = useState<
    "none" | "loading" | "valid" | "invalid"
  >(inviteToken ? "loading" : "none");
  const [inviteError, setInviteError] = useState<string | null>(null);

  // When an invite token is present, prefill + lock the email field. If the
  // token is bad we surface that immediately rather than waiting for submit.
  useEffect(() => {
    if (!inviteToken) return;
    let cancelled = false;
    lookupInvitation(inviteToken)
      .then((info) => {
        if (cancelled) return;
        setEmail(info.email);
        setInviteStatus("valid");
      })
      .catch((err) => {
        if (cancelled) return;
        setInviteStatus("invalid");
        setInviteError(
          err instanceof Error ? err.message : null
        );
      });
    return () => {
      cancelled = true;
    };
  }, [inviteToken]);

  const validate = useCallback((): boolean => {
    const newErrors: FormErrors = {};

    if (!email) {
      newErrors.email = "Type your email.";
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      newErrors.email = "That email doesn't look right.";
    }

    if (!username) {
      newErrors.username = "Pick a username.";
    } else if (username.length < 3) {
      newErrors.username = "Use at least 3 characters.";
    } else if (!/^[a-zA-Z0-9_]+$/.test(username)) {
      newErrors.username = "Use only letters, numbers and _.";
    }

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
  }, [email, username, password, confirmPassword]);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();

      if (!validate()) return;

      setIsSubmitting(true);
      setErrors({});

      try {
        if (isUpgrade && isAnonymous) {
          await upgradeAccount(email, username, password);
        } else {
          await register(email, username, password, inviteToken ?? undefined);
        }
        router.push(decodeURIComponent(returnUrl));
      } catch (err) {
        setErrors({
          general:
            err instanceof Error ? err.message : "Couldn't sign up. Try again.",
        });
      } finally {
        setIsSubmitting(false);
      }
    },
    [
      email,
      username,
      password,
      register,
      upgradeAccount,
      isUpgrade,
      isAnonymous,
      inviteToken,
      router,
      returnUrl,
      validate,
    ]
  );

  const hasInvite = inviteStatus === "valid";
  const subtitle = hasInvite
    ? `You're invited as ${email}.`
    : isUpgrade && isAnonymous
      ? "Keep the games you made."
      : null;

  return (
    <div className="w-full max-w-md rounded-lg bg-surface-raised brutal-card p-6">
      <h2 className="font-[family-name:var(--font-heading)] text-3xl font-bold text-center">
        Sign up
      </h2>
      {subtitle && (
        <p className="text-center text-sm text-txt-secondary mt-1">{subtitle}</p>
      )}

      <form onSubmit={handleSubmit} className="mt-6 space-y-4">
        {inviteStatus === "loading" && (
          <div className="rounded-md border-2 border-pop-cyan bg-pop-cyan/10 p-3 text-xs font-bold uppercase tracking-wider text-pop-cyan">
            Checking your invite…
          </div>
        )}
        {inviteStatus === "invalid" && (
          <div
            className="rounded-md border-2 border-pop-red bg-pop-red/10 p-3 text-sm font-bold text-pop-red"
            role="alert"
          >
            {inviteError ?? "This invite doesn't work. Ask for a new one."}
          </div>
        )}
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
            disabled={isSubmitting || hasInvite}
            readOnly={hasInvite}
            className={inputClass}
          />
          {errors.email && (
            <p className="text-xs font-bold text-pop-red">{errors.email}</p>
          )}
        </div>

        <div className="space-y-1.5">
          <label
            htmlFor="username"
            className="block text-xs font-bold uppercase tracking-wider text-txt-secondary"
          >
            Username
          </label>
          <input
            id="username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="coolcreator"
            aria-invalid={!!errors.username}
            disabled={isSubmitting}
            className={inputClass}
          />
          {errors.username && (
            <p className="text-xs font-bold text-pop-red">{errors.username}</p>
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
            <p className="text-xs font-bold text-pop-red">
              {errors.confirmPassword}
            </p>
          )}
        </div>

        <button
          type="submit"
          disabled={isSubmitting}
          className="w-full rounded-md bg-pop-yellow px-4 py-3 text-sm font-bold uppercase tracking-wider text-surface brutal-border transition-colors hover:bg-pop-lime cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isSubmitting ? "Signing up…" : "Sign up"}
        </button>
      </form>

      {!isUpgrade && (
        <div className="mt-6 pt-4 border-t-2 border-[var(--card-border)] text-center">
          <p className="text-xs font-bold uppercase tracking-wider text-txt-muted">
            Have an account?{" "}
            <Link
              href="/login"
              className="text-pop-yellow hover:text-pop-lime transition-colors"
            >
              Sign in
            </Link>
          </p>
        </div>
      )}
    </div>
  );
}
