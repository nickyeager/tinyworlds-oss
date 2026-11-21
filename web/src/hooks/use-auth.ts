"use client";

import { useContext } from "react";
import { AuthContext, type AuthContextValue } from "@/components/auth/auth-provider";

/**
 * Hook to access authentication state and actions
 *
 * @example
 * ```tsx
 * const { user, isAuthenticated, login, logout, ensureToken } = useAuth();
 *
 * // Check auth status
 * if (isAuthenticated) {
 *   console.log(`Logged in as ${user?.email}`);
 * }
 *
 * // Get token for API calls (creates anonymous if needed)
 * const token = await ensureToken();
 * await createGame(intent, token);
 * ```
 */
export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);

  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }

  return context;
}
