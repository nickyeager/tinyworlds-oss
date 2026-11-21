"use client";

import { useState, useRef, useEffect, type ReactNode } from "react";
import Link from "next/link";
import { Save, UsersRound } from "lucide-react";

const menuItem = "block px-4 py-2 text-sm font-bold hover:bg-surface cursor-pointer";
import { useAuth } from "@/hooks/use-auth";

function BrutalAuthControl() {
  const {
    user,
    isAuthenticated,
    isAnonymous,
    logout,
    isLoading,
    sessionExpired,
    dismissSessionExpired,
  } = useAuth();
  const [isOpen, setIsOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  if (isLoading) {
    return (
      <div
        className="h-9 w-9 animate-pulse rounded-md bg-surface-raised brutal-border"
        data-testid="user-menu"
      />
    );
  }

  // Account creation remains available from the sign-in screen.
  if (!isAuthenticated) {
    return (
      <div className="flex items-center gap-2 shrink-0" data-testid="user-menu">
        {sessionExpired && (
          <span
            className="hidden md:inline text-xs font-bold uppercase tracking-wider text-pop-red whitespace-nowrap"
            data-testid="session-expired-notice"
          >
            Signed out
          </span>
        )}
        <Link
          href="/login"
          onClick={sessionExpired ? dismissSessionExpired : undefined}
          className={`${sessionExpired ? "text-pop-red hover:text-pop-yellow" : "text-txt-secondary hover:text-pop-yellow"} text-sm font-bold uppercase tracking-wider whitespace-nowrap transition-colors`}
        >
          {sessionExpired ? "Sign in again" : "Sign in"}
        </Link>
      </div>
    );
  }

  // Admin link surfaced beside the avatar when the user has the flag.
  const adminLink = !isAnonymous && user?.is_admin ? (
    <Link
      href="/admin"
      className="text-sm font-bold uppercase tracking-wider text-pop-yellow transition-colors hover:text-pop-lime"
    >
      Admin
    </Link>
  ) : null;

  // Guests see a Save icon ("sign up to keep your games"); signed-in users
  // see their initial.
  const registeredInitial = (
    user?.email?.[0] ?? user?.username?.[0] ?? "U"
  ).toUpperCase();

  const handleLogout = async () => {
    setIsOpen(false);
    await logout();
  };

  return (
    <div className="flex items-center gap-4">
      {adminLink}
      {isAnonymous && (
        <Link
          href="/login"
          className="sm:hidden text-sm font-bold uppercase tracking-wider whitespace-nowrap text-txt-secondary transition-colors hover:text-pop-yellow"
        >
          Sign in
        </Link>
      )}
      <div className="relative" ref={menuRef} data-testid="user-menu">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`flex h-9 w-9 items-center justify-center rounded-md font-bold brutal-border transition-colors cursor-pointer ${
          isAnonymous
            ? "bg-pop-yellow/20 text-pop-yellow hover:bg-pop-yellow/30"
            : "bg-pop-cyan/20 text-pop-cyan hover:bg-pop-cyan/30"
        }`}
        aria-label={isAnonymous ? "Keep your games" : "Your account"}
        title={isAnonymous ? "Keep your games" : undefined}
        data-testid="user-menu-trigger"
      >
        {isAnonymous ? <Save className="h-4 w-4" /> : registeredInitial}
      </button>

      {isOpen && (
        <div className="absolute right-0 top-11 w-60 rounded-md bg-surface-raised brutal-card py-1 z-50">
          {isAnonymous ? (
            <>
              <div className="px-4 py-2 text-xs font-bold uppercase tracking-wider text-txt-muted border-b-2 border-[var(--card-border)]">
                Guest
              </div>
              <Link
                href="/register?upgrade=true"
                className={`${menuItem} text-pop-yellow`}
                onClick={() => setIsOpen(false)}
                data-testid="user-menu-create-account"
              >
                Sign up
              </Link>
              <Link
                href="/login"
                className={`${menuItem} text-pop-cyan`}
                onClick={() => setIsOpen(false)}
                data-testid="user-menu-sign-in"
              >
                Sign in
              </Link>
              <p className="px-4 py-2 text-xs text-txt-muted">
                Sign up to keep your games.
              </p>
            </>
          ) : (
            <div className="px-4 py-2">
              <p className="text-sm font-bold truncate">{user?.username}</p>
              <p className="text-xs text-txt-muted truncate">{user?.email}</p>
            </div>
          )}

          <button
            onClick={handleLogout}
            className={`${menuItem} w-full text-left uppercase tracking-wider text-pop-red border-t-2 border-[var(--card-border)]`}
          >
            Sign out
          </button>
        </div>
      )}
      </div>
    </div>
  );
}

interface SiteNavProps {
  /** Page-specific items rendered between the logo and the auth control. */
  children?: ReactNode;
  /** Compact variant used on the game detail page (smaller logo, bordered). */
  compact?: boolean;
  /** Hide account management during focused gameplay. */
  showAccount?: boolean;
}

export function SiteNav({ children, compact = false, showAccount = true }: SiteNavProps) {
  const logoSize = compact ? "h-8 w-8" : "h-9 w-9";
  const iconSize = compact ? "h-4 w-4" : "h-5 w-5";
  const titleSize = compact ? "text-base sm:text-xl" : "text-lg sm:text-2xl";
  const navPad = compact
    ? "px-3 py-3 sm:px-6 sm:py-4 border-b-2 border-[var(--card-border)]"
    : "px-3 py-3 sm:px-8 sm:py-5";

  return (
    <nav className={`flex items-center justify-between gap-2 ${navPad}`}>
      <Link href="/create" aria-label="TinyWorlds" className="flex items-center gap-2 sm:gap-3 min-w-0">
        <div
          className={`flex ${logoSize} items-center justify-center rounded-md bg-pop-yellow brutal-border brutal-shadow`}
        >
          <svg
            className={`${iconSize} text-surface`}
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            viewBox="0 0 24 24"
          >
            <path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z" />
          </svg>
        </div>
        <span
          className={`font-[family-name:var(--font-heading)] ${titleSize} font-bold tracking-tight ${compact ? "hidden min-[420px]:inline" : ""}`}
        >
          TinyWorlds
        </span>
      </Link>
      <div className="flex items-center gap-2 sm:gap-4 min-w-0">
        {!compact && <Link href="/agent-play" aria-label="Play with Pip" className="flex shrink-0 items-center text-sm font-bold text-txt-secondary hover:text-pop-cyan"><UsersRound className="size-5 sm:hidden" /><span className="hidden sm:inline">Play with Pip</span></Link>}
        {children}
        {showAccount && <BrutalAuthControl />}
      </div>
    </nav>
  );
}
