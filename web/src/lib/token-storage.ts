/**
 * Token storage utilities for authentication
 *
 * Stores tokens in localStorage for persistence across page refreshes.
 * Includes expiry tracking for automatic refresh handling.
 */

const ACCESS_TOKEN_KEY = "tinyworlds_access_token";
const TOKEN_EXPIRY_KEY = "tinyworlds_token_expiry";
const USER_KEY = "tinyworlds_user";

export interface StoredUser {
  id: string;
  email: string | null;
  username: string;
  isAnonymous: boolean;
}

/**
 * Save access token with expiry time
 */
export function saveToken(token: string, expiresInSeconds: number): void {
  if (typeof window === "undefined") return;

  const expiresAt = Date.now() + expiresInSeconds * 1000;
  localStorage.setItem(ACCESS_TOKEN_KEY, token);
  localStorage.setItem(TOKEN_EXPIRY_KEY, expiresAt.toString());
}

/**
 * Get stored access token if valid
 * Returns null if token is missing or expired
 */
export function getToken(): string | null {
  if (typeof window === "undefined") return null;

  const token = localStorage.getItem(ACCESS_TOKEN_KEY);
  const expiresAt = localStorage.getItem(TOKEN_EXPIRY_KEY);

  if (!token || !expiresAt) return null;

  // Check if expired (with 60s buffer)
  if (Date.now() > parseInt(expiresAt) - 60000) {
    clearToken();
    return null;
  }

  return token;
}

/**
 * Clear stored token
 */
export function clearToken(): void {
  if (typeof window === "undefined") return;

  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(TOKEN_EXPIRY_KEY);
}

/**
 * Check if token is expiring soon (within 5 minutes)
 */
export function isTokenExpiringSoon(): boolean {
  if (typeof window === "undefined") return true;

  const expiresAt = localStorage.getItem(TOKEN_EXPIRY_KEY);
  if (!expiresAt) return true;

  // Refresh if less than 5 minutes remaining
  return Date.now() > parseInt(expiresAt) - 300000;
}

/**
 * Save user data to localStorage
 */
export function saveUser(user: StoredUser): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

/**
 * Get stored user data
 */
export function getUser(): StoredUser | null {
  if (typeof window === "undefined") return null;

  const userData = localStorage.getItem(USER_KEY);
  if (!userData) return null;

  try {
    return JSON.parse(userData);
  } catch {
    return null;
  }
}

/**
 * Clear stored user data
 */
export function clearUser(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(USER_KEY);
}

/**
 * Clear all auth data
 */
export function clearAllAuthData(): void {
  clearToken();
  clearUser();
}
