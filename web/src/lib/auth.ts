/**
 * Authentication API functions
 */
import { formatApiError } from "./api-errors";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

export interface User {
  id: string;
  email: string;
  username: string;
  full_name: string | null;
  is_active: boolean;
  is_anonymous: boolean;
  is_admin: boolean;
  created_at: string;
  updated_at: string;
}

export interface InvitationLookup {
  email: string;
  expires_at: string;
}

export interface Invitation {
  id: string;
  email: string;
  token: string;
  accept_url: string;
  created_at: string;
  expires_at: string;
  accepted_at: string | null;
  accepted_by_user_id: string | null;
  email_sent: boolean | null;
}

export async function lookupInvitation(token: string): Promise<InvitationLookup> {
  const response = await fetch(
    `${API_BASE}/api/v1/auth/invitation/${encodeURIComponent(token)}`
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(formatApiError(error, "Invite lookup failed"));
  }
  return response.json();
}

export async function listInvitations(authToken: string): Promise<Invitation[]> {
  const response = await fetch(`${API_BASE}/api/v1/admin/invitations`, {
    headers: { Authorization: `Bearer ${authToken}` },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(formatApiError(error, "Failed to load invitations"));
  }
  const data = await response.json();
  return data.invitations;
}

export async function createInvitation(
  email: string,
  authToken: string,
  sendEmail: boolean = true
): Promise<Invitation> {
  const response = await fetch(`${API_BASE}/api/v1/admin/invitations`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${authToken}`,
    },
    body: JSON.stringify({ email, send_email: sendEmail }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(formatApiError(error, "Failed to create invitation"));
  }
  return response.json();
}

export async function resendInvitation(
  invitationId: string,
  authToken: string
): Promise<Invitation> {
  const response = await fetch(
    `${API_BASE}/api/v1/admin/invitations/${invitationId}/resend`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${authToken}` },
    }
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(formatApiError(error, "Failed to resend invitation"));
  }
  return response.json();
}

// ---- Admin Users ----

export interface AdminUser {
  id: string;
  email: string;
  username: string;
  full_name: string | null;
  is_active: boolean;
  is_admin: boolean;
  is_anonymous: boolean;
  scheduled_deletion_at: string | null;
  created_at: string;
  last_seen_at: string | null;
  active_session_count: number;
  game_count: number;
}

export interface AdminUserListResponse {
  users: AdminUser[];
  next_cursor: string | null;
  total: number;
}

export interface AdminSession {
  id: string;
  device_name: string | null;
  device_type: string | null;
  user_agent: string | null;
  ip_address: string | null;
  is_active: boolean;
  last_active_at: string;
  created_at: string;
  revoked_at: string | null;
}

export async function listUsers(
  authToken: string,
  params: {
    q?: string;
    include_anonymous?: boolean;
    is_admin?: boolean;
    is_active?: boolean;
    cursor?: string;
    limit?: number;
  } = {}
): Promise<AdminUserListResponse> {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.include_anonymous) qs.set("include_anonymous", "true");
  if (params.is_admin !== undefined) qs.set("is_admin", String(params.is_admin));
  if (params.is_active !== undefined) qs.set("is_active", String(params.is_active));
  if (params.cursor) qs.set("cursor", params.cursor);
  if (params.limit) qs.set("limit", String(params.limit));
  const url = `${API_BASE}/api/v1/admin/users${qs.toString() ? "?" + qs.toString() : ""}`;
  const response = await fetch(url, {
    headers: { Authorization: `Bearer ${authToken}` },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(formatApiError(error, "Failed to load users"));
  }
  return response.json();
}

export async function updateUser(
  userId: string,
  authToken: string,
  patch: { is_active?: boolean; is_admin?: boolean }
): Promise<AdminUser> {
  const response = await fetch(`${API_BASE}/api/v1/admin/users/${userId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${authToken}`,
    },
    body: JSON.stringify(patch),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(formatApiError(error, "Failed to update user"));
  }
  return response.json();
}

export async function deleteUser(
  userId: string,
  authToken: string
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/v1/admin/users/${userId}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${authToken}` },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(formatApiError(error, "Failed to delete user"));
  }
}

export async function triggerPasswordReset(
  userId: string,
  authToken: string,
  sendEmail: boolean = true
): Promise<{ expires_at: string; email_sent: boolean; reset_url: string | null }> {
  const response = await fetch(
    `${API_BASE}/api/v1/admin/users/${userId}/password-reset`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${authToken}`,
      },
      body: JSON.stringify({ send_email: sendEmail }),
    }
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(formatApiError(error, "Failed to trigger password reset"));
  }
  return response.json();
}

export async function listUserSessions(
  userId: string,
  authToken: string,
  activeOnly: boolean = true
): Promise<AdminSession[]> {
  const url = `${API_BASE}/api/v1/admin/users/${userId}/sessions?active_only=${activeOnly}`;
  const response = await fetch(url, {
    headers: { Authorization: `Bearer ${authToken}` },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(formatApiError(error, "Failed to load sessions"));
  }
  const data = await response.json();
  return data.sessions;
}

export async function revokeUserSession(
  userId: string,
  sessionId: string,
  authToken: string
): Promise<void> {
  const response = await fetch(
    `${API_BASE}/api/v1/admin/users/${userId}/sessions/${sessionId}`,
    {
      method: "DELETE",
      headers: { Authorization: `Bearer ${authToken}` },
    }
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(formatApiError(error, "Failed to revoke session"));
  }
}

export async function revokeAllUserSessions(
  userId: string,
  authToken: string
): Promise<void> {
  const response = await fetch(
    `${API_BASE}/api/v1/admin/users/${userId}/sessions/revoke-all`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${authToken}` },
    }
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(formatApiError(error, "Failed to revoke sessions"));
  }
}

export async function deleteInvitation(
  invitationId: string,
  authToken: string
): Promise<void> {
  const response = await fetch(
    `${API_BASE}/api/v1/admin/invitations/${invitationId}`,
    {
      method: "DELETE",
      headers: { Authorization: `Bearer ${authToken}` },
    }
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(formatApiError(error, "Failed to revoke invitation"));
  }
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user_id: string;
  is_anonymous: boolean;
}

/**
 * Register a new user
 */
export async function register(
  email: string,
  username: string,
  password: string,
  inviteToken?: string
): Promise<AuthResponse> {
  const body: Record<string, string> = { email, username, password };
  if (inviteToken) body.invite_token = inviteToken;
  const response = await fetch(`${API_BASE}/api/v1/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(formatApiError(error, "Registration failed"));
  }

  return response.json();
}

/**
 * Login with email and password (JSON body)
 */
export async function login(email: string, password: string): Promise<AuthResponse> {
  const response = await fetch(`${API_BASE}/api/v1/auth/login/json`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(formatApiError(error, "Invalid email or password"));
  }

  return response.json();
}

/**
 * Get anonymous token for guest access
 */
export async function getAnonymousToken(): Promise<AuthResponse> {
  const response = await fetch(`${API_BASE}/api/v1/auth/anonymous`, {
    method: "POST",
  });

  if (!response.ok) {
    throw new Error("Failed to get anonymous token");
  }

  return response.json();
}

/**
 * Upgrade anonymous account to registered
 */
export async function upgradeAccount(
  token: string,
  email: string,
  username: string,
  password: string
): Promise<AuthResponse> {
  const response = await fetch(`${API_BASE}/api/v1/auth/upgrade`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ email, username, password }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(formatApiError(error, "Account upgrade failed"));
  }

  return response.json();
}

/**
 * Get current user info
 */
export async function getCurrentUser(token: string): Promise<User> {
  const response = await fetch(`${API_BASE}/api/v1/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!response.ok) {
    throw new Error("Failed to get current user");
  }

  return response.json();
}

/**
 * Logout (server-side notification)
 */
export async function logout(token: string): Promise<void> {
  await fetch(`${API_BASE}/api/v1/auth/logout`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
}

/**
 * Request password reset email
 */
export async function requestPasswordReset(email: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/v1/auth/forgot-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(formatApiError(error, "Failed to send reset email"));
  }
}

/**
 * Reset password with token
 */
export async function resetPassword(token: string, newPassword: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/v1/auth/reset-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, password: newPassword }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(formatApiError(error, "Password reset failed"));
  }
}
