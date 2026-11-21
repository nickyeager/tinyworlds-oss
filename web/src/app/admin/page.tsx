"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/hooks/use-auth";
import { SiteNav } from "@/components/site-nav";
import {
  AdminUser,
  Invitation,
  createInvitation,
  deleteInvitation,
  deleteUser,
  listInvitations,
  listUsers,
  resendInvitation,
  revokeAllUserSessions,
  triggerPasswordReset,
  updateUser,
} from "@/lib/auth";
import {
  Loader2,
  Copy,
  Check,
  Trash2,
  Mail,
  Send,
  KeyRound,
  Shield,
  ShieldOff,
  UserX,
  UserCheck,
  LogOut,
} from "lucide-react";

type Tab = "invitations" | "users";

function formatDate(iso: string | null) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function inviteStatus(invitation: Invitation): {
  label: string;
  className: string;
} {
  if (invitation.accepted_at)
    return { label: "Accepted", className: "bg-pop-lime/20 text-pop-lime" };
  if (new Date(invitation.expires_at) < new Date())
    return { label: "Expired", className: "bg-pop-red/20 text-pop-red" };
  return { label: "Pending", className: "bg-pop-yellow/20 text-pop-yellow" };
}

export default function AdminPage() {
  const { user, token, isLoading: authLoading } = useAuth();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("users");

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      router.replace("/login?returnUrl=" + encodeURIComponent("/admin"));
      return;
    }
    if (!user.is_admin) {
      router.replace("/create");
    }
  }, [user, authLoading, router]);

  if (authLoading || !user || !user.is_admin) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface">
        <Loader2 className="h-5 w-5 animate-spin text-pop-yellow" />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col bg-surface text-txt-primary selection:bg-pop-yellow/30">
      <SiteNav>
        <Link
          href="/create"
          className="text-sm font-bold uppercase tracking-wider text-txt-secondary transition-colors hover:text-pop-yellow"
        >
          Back to App
        </Link>
      </SiteNav>

      <main className="flex flex-1 flex-col px-8 pb-16 max-w-6xl w-full mx-auto">
        <div className="mb-6">
          <h1 className="font-[family-name:var(--font-heading)] text-4xl font-bold">
            Admin
          </h1>
          <p className="mt-1 font-mono text-sm font-bold text-txt-secondary uppercase tracking-wider">
            User management & invitations
          </p>
        </div>

        <div className="mb-6 flex gap-2 border-b-2 border-black">
          <TabButton active={tab === "users"} onClick={() => setTab("users")}>
            Users
          </TabButton>
          <TabButton
            active={tab === "invitations"}
            onClick={() => setTab("invitations")}
          >
            Invitations
          </TabButton>
        </div>

        {tab === "users" && token && <UsersTab token={token} currentUserId={user.id} />}
        {tab === "invitations" && token && <InvitationsTab token={token} />}
      </main>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 -mb-[2px] text-sm font-bold uppercase tracking-wider border-b-4 transition-colors ${
        active
          ? "border-pop-yellow text-txt-primary"
          : "border-transparent text-txt-secondary hover:text-txt-primary"
      }`}
    >
      {children}
    </button>
  );
}

// ============== Users Tab ==============

function UsersTab({ token, currentUserId }: { token: string; currentUserId: string }) {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [q, setQ] = useState("");
  const [showAnonymous, setShowAnonymous] = useState(false);
  const [adminsOnly, setAdminsOnly] = useState(false);
  const [busyUserId, setBusyUserId] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const load = useCallback(
    async (cursor?: string) => {
      setLoading(true);
      setError(null);
      try {
        const data = await listUsers(token, {
          q: q.trim() || undefined,
          include_anonymous: showAnonymous,
          is_admin: adminsOnly ? true : undefined,
          cursor,
          limit: 50,
        });
        setUsers((prev) => (cursor ? [...prev, ...data.users] : data.users));
        setNextCursor(data.next_cursor);
        setTotal(data.total);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load users");
      } finally {
        setLoading(false);
      }
    },
    [token, q, showAnonymous, adminsOnly]
  );

  useEffect(() => {
    const t = setTimeout(() => load(), 250);
    return () => clearTimeout(t);
  }, [load]);

  const flash = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2200);
  };

  const handleSendReset = async (u: AdminUser) => {
    if (!confirm(`Email a password-reset link to ${u.email}?`)) return;
    setBusyUserId(u.id);
    try {
      const res = await triggerPasswordReset(u.id, token, true);
      flash(res.email_sent ? "Reset email sent" : "Reset created (email failed)");
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed");
    } finally {
      setBusyUserId(null);
    }
  };

  const handleToggleActive = async (u: AdminUser) => {
    const next = !u.is_active;
    if (!next && !confirm(`Deactivate ${u.email}? Their sessions will be revoked.`))
      return;
    setBusyUserId(u.id);
    try {
      const updated = await updateUser(u.id, token, { is_active: next });
      setUsers((prev) => prev.map((x) => (x.id === u.id ? updated : x)));
      flash(next ? "User activated" : "User deactivated");
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed");
    } finally {
      setBusyUserId(null);
    }
  };

  const handleToggleAdmin = async (u: AdminUser) => {
    const next = !u.is_admin;
    const msg = next
      ? `Promote ${u.email} to admin?`
      : `Demote ${u.email} from admin?`;
    if (!confirm(msg)) return;
    setBusyUserId(u.id);
    try {
      const updated = await updateUser(u.id, token, { is_admin: next });
      setUsers((prev) => prev.map((x) => (x.id === u.id ? updated : x)));
      flash(next ? "Promoted to admin" : "Demoted from admin");
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed");
    } finally {
      setBusyUserId(null);
    }
  };

  const handleRevokeAll = async (u: AdminUser) => {
    if (!confirm(`Force-logout all sessions for ${u.email}?`)) return;
    setBusyUserId(u.id);
    try {
      await revokeAllUserSessions(u.id, token);
      setUsers((prev) =>
        prev.map((x) => (x.id === u.id ? { ...x, active_session_count: 0 } : x))
      );
      flash("All sessions revoked");
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed");
    } finally {
      setBusyUserId(null);
    }
  };

  const handleDelete = async (u: AdminUser) => {
    if (
      !confirm(
        `DELETE ${u.email} permanently? This cascades to their games and sessions. This cannot be undone.`
      )
    )
      return;
    setBusyUserId(u.id);
    try {
      await deleteUser(u.id, token);
      setUsers((prev) => prev.filter((x) => x.id !== u.id));
      setTotal((t) => Math.max(0, t - 1));
      flash("User deleted");
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed");
    } finally {
      setBusyUserId(null);
    }
  };

  return (
    <>
      {toast && (
        <div className="fixed bottom-6 right-6 z-50 rounded-md bg-pop-lime px-4 py-2 text-sm font-bold text-surface brutal-border">
          {toast}
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input
          type="search"
          placeholder="Search email, username, or name…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="flex-1 min-w-[240px] rounded-md bg-surface-raised px-3 py-2 text-sm font-bold brutal-border focus:outline-none focus:border-pop-yellow"
        />
        <label className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-txt-secondary">
          <input
            type="checkbox"
            checked={showAnonymous}
            onChange={(e) => setShowAnonymous(e.target.checked)}
          />
          Show anonymous
        </label>
        <label className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-txt-secondary">
          <input
            type="checkbox"
            checked={adminsOnly}
            onChange={(e) => setAdminsOnly(e.target.checked)}
          />
          Admins only
        </label>
        <span className="font-mono text-xs font-bold uppercase tracking-wider text-txt-muted">
          {total} total
        </span>
      </div>

      {error && (
        <div className="mb-4 rounded-md border-2 border-pop-red bg-pop-red/10 p-3 text-sm font-bold text-pop-red">
          {error}
        </div>
      )}

      <div className="rounded-md bg-surface-raised brutal-card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-surface border-b-2 border-black">
            <tr className="text-left text-xs font-bold uppercase tracking-wider text-txt-secondary">
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3">Username</th>
              <th className="px-4 py-3">Created</th>
              <th className="px-4 py-3">Last seen</th>
              <th className="px-4 py-3 text-center">Sessions</th>
              <th className="px-4 py-3 text-center">Games</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => {
              const busy = busyUserId === u.id;
              const isSelf = u.id === currentUserId;
              return (
                <tr
                  key={u.id}
                  className={`border-t-2 border-black/10 ${
                    !u.is_active ? "opacity-60" : ""
                  }`}
                >
                  <td className="px-4 py-3 font-bold truncate max-w-[240px]">
                    {u.email}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs">{u.username}</td>
                  <td className="px-4 py-3 font-mono text-xs">
                    {formatDate(u.created_at)}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs">
                    {formatDate(u.last_seen_at)}
                  </td>
                  <td className="px-4 py-3 text-center font-mono">
                    {u.active_session_count}
                  </td>
                  <td className="px-4 py-3 text-center font-mono">
                    {u.game_count}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {u.is_admin && (
                        <span className="tag bg-pop-yellow/20 text-pop-yellow">
                          Admin
                        </span>
                      )}
                      {u.is_anonymous && (
                        <span className="tag bg-pop-cyan/20 text-pop-cyan">
                          Anon
                        </span>
                      )}
                      {!u.is_active && (
                        <span className="tag bg-pop-red/20 text-pop-red">
                          Inactive
                        </span>
                      )}
                      {u.scheduled_deletion_at && (
                        <span className="tag bg-pop-red/20 text-pop-red">
                          Pending del
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-1.5">
                      <RowButton
                        title="Send password reset"
                        onClick={() => handleSendReset(u)}
                        disabled={busy || u.is_anonymous || !u.is_active}
                      >
                        <KeyRound className="h-3.5 w-3.5" />
                      </RowButton>
                      <RowButton
                        title="Force logout"
                        onClick={() => handleRevokeAll(u)}
                        disabled={busy || u.active_session_count === 0}
                      >
                        <LogOut className="h-3.5 w-3.5" />
                      </RowButton>
                      <RowButton
                        title={u.is_active ? "Deactivate" : "Reactivate"}
                        onClick={() => handleToggleActive(u)}
                        disabled={busy || isSelf}
                      >
                        {u.is_active ? (
                          <UserX className="h-3.5 w-3.5" />
                        ) : (
                          <UserCheck className="h-3.5 w-3.5" />
                        )}
                      </RowButton>
                      <RowButton
                        title={u.is_admin ? "Demote admin" : "Promote to admin"}
                        onClick={() => handleToggleAdmin(u)}
                        disabled={busy || isSelf || u.is_anonymous}
                      >
                        {u.is_admin ? (
                          <ShieldOff className="h-3.5 w-3.5" />
                        ) : (
                          <Shield className="h-3.5 w-3.5" />
                        )}
                      </RowButton>
                      <RowButton
                        title="Delete user"
                        onClick={() => handleDelete(u)}
                        disabled={busy || isSelf}
                        danger
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </RowButton>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-4 flex items-center justify-center">
        {loading ? (
          <Loader2 className="h-5 w-5 animate-spin text-pop-yellow" />
        ) : nextCursor ? (
          <button
            onClick={() => load(nextCursor)}
            className="rounded-md bg-surface-raised brutal-border px-5 py-2 text-xs font-bold uppercase tracking-wider hover:bg-pop-yellow/20"
          >
            Load more
          </button>
        ) : users.length > 0 ? (
          <span className="font-mono text-xs text-txt-muted">End of list</span>
        ) : (
          <span className="font-mono text-xs text-txt-muted">No users</span>
        )}
      </div>
    </>
  );
}

function RowButton({
  title,
  onClick,
  disabled,
  danger,
  children,
}: {
  title: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
  children: React.ReactNode;
}) {
  const base =
    "flex items-center justify-center rounded-md border-2 px-2 py-1.5 transition-colors disabled:opacity-30 disabled:cursor-not-allowed";
  const tone = danger
    ? "border-pop-red text-pop-red hover:bg-pop-red/10"
    : "border-black text-txt-primary hover:bg-pop-yellow/20";
  return (
    <button
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={`${base} ${tone}`}
    >
      {children}
    </button>
  );
}

// ============== Invitations Tab ==============

function InvitationsTab({ token }: { token: string }) {
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [emailInput, setEmailInput] = useState("");
  const [sendEmail, setSendEmail] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const list = await listInvitations(token);
      setInvitations(list);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Failed to load invites");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const flash = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2200);
  };

  const handleCreate = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!emailInput.trim()) return;
      setSubmitting(true);
      setSubmitError(null);
      try {
        const invite = await createInvitation(emailInput.trim(), token, sendEmail);
        setInvitations((prev) => {
          const filtered = prev.filter((i) => i.id !== invite.id);
          return [invite, ...filtered];
        });
        setEmailInput("");
        if (sendEmail) {
          flash(invite.email_sent ? "Invite email sent" : "Invite created (email failed)");
        } else {
          flash("Invite link ready to copy");
        }
      } catch (err) {
        setSubmitError(err instanceof Error ? err.message : "Failed to create invite");
      } finally {
        setSubmitting(false);
      }
    },
    [emailInput, sendEmail, token]
  );

  const handleCopy = useCallback(async (invitation: Invitation) => {
    await navigator.clipboard.writeText(invitation.accept_url);
    setCopiedId(invitation.id);
    setTimeout(() => setCopiedId((id) => (id === invitation.id ? null : id)), 1500);
  }, []);

  const handleResend = useCallback(
    async (invitation: Invitation) => {
      try {
        const updated = await resendInvitation(invitation.id, token);
        setInvitations((prev) =>
          prev.map((i) => (i.id === updated.id ? updated : i))
        );
        flash(updated.email_sent ? "Email re-sent" : "Resend failed");
      } catch (err) {
        alert(err instanceof Error ? err.message : "Failed");
      }
    },
    [token]
  );

  const handleRevoke = useCallback(
    async (invitation: Invitation) => {
      if (
        !confirm(`Revoke invite for ${invitation.email}? The link will stop working.`)
      )
        return;
      try {
        await deleteInvitation(invitation.id, token);
        setInvitations((prev) => prev.filter((i) => i.id !== invitation.id));
      } catch (err) {
        alert(err instanceof Error ? err.message : "Failed to revoke");
      }
    },
    [token]
  );

  return (
    <>
      {toast && (
        <div className="fixed bottom-6 right-6 z-50 rounded-md bg-pop-lime px-4 py-2 text-sm font-bold text-surface brutal-border">
          {toast}
        </div>
      )}

      <div className="mb-8 rounded-lg bg-surface-raised brutal-card p-5">
        <form onSubmit={handleCreate} className="flex flex-col gap-3">
          <label
            htmlFor="invite-email"
            className="text-xs font-bold uppercase tracking-wider text-txt-secondary"
          >
            Invite an email
          </label>
          <div className="flex gap-3">
            <div className="relative flex-1">
              <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-txt-muted" />
              <input
                id="invite-email"
                type="email"
                value={emailInput}
                onChange={(e) => setEmailInput(e.target.value)}
                placeholder="newuser@example.com"
                disabled={submitting}
                required
                className="w-full rounded-md bg-surface px-3 py-2.5 pl-10 text-sm font-bold brutal-border focus:outline-none focus:border-pop-yellow disabled:opacity-50 transition-colors"
              />
            </div>
            <button
              type="submit"
              disabled={submitting || !emailInput.trim()}
              className="rounded-md bg-pop-yellow px-5 py-2.5 text-sm font-bold uppercase tracking-wider text-surface brutal-border hover:bg-pop-lime disabled:opacity-50 whitespace-nowrap"
            >
              {submitting ? "Issuing..." : sendEmail ? "Send Invite" : "Create Link"}
            </button>
          </div>
          <label className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-txt-secondary">
            <input
              type="checkbox"
              checked={sendEmail}
              onChange={(e) => setSendEmail(e.target.checked)}
            />
            Email the invite (uncheck for copy-link only)
          </label>
          {submitError && (
            <p className="text-xs font-bold text-pop-red">{submitError}</p>
          )}
        </form>
      </div>

      <div className="mb-2 flex items-center justify-between">
        <h2 className="font-[family-name:var(--font-heading)] text-xl font-bold">
          All invites
        </h2>
        <span className="font-mono text-xs font-bold uppercase tracking-wider text-txt-muted">
          {invitations.length} total
        </span>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-5 w-5 animate-spin text-pop-yellow" />
        </div>
      ) : loadError ? (
        <div className="rounded-md border-2 border-pop-red bg-pop-red/10 p-4 text-sm font-bold text-pop-red">
          {loadError}
        </div>
      ) : invitations.length === 0 ? (
        <div className="rounded-md bg-surface-raised brutal-card p-8 text-center">
          <p className="font-mono text-sm font-bold text-txt-muted">
            No invites yet. Issue one above.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {invitations.map((invitation) => {
            const status = inviteStatus(invitation);
            const isAccepted = !!invitation.accepted_at;
            return (
              <div
                key={invitation.id}
                className="rounded-md bg-surface-raised brutal-card p-4 flex items-center gap-4"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3 mb-1">
                    <span className="font-bold truncate">{invitation.email}</span>
                    <span className={`tag ${status.className}`}>{status.label}</span>
                  </div>
                  <p className="font-mono text-xs text-txt-muted">
                    issued {formatDate(invitation.created_at)} · expires{" "}
                    {formatDate(invitation.expires_at)}
                    {isAccepted &&
                      ` · accepted ${formatDate(invitation.accepted_at!)}`}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {!isAccepted && (
                    <>
                      <button
                        onClick={() => handleCopy(invitation)}
                        title="Copy invite link"
                        className="flex items-center gap-1.5 rounded-md bg-pop-cyan/10 border-2 border-pop-cyan px-3 py-1.5 text-xs font-bold uppercase tracking-wider text-pop-cyan hover:bg-pop-cyan/20"
                      >
                        {copiedId === invitation.id ? (
                          <>
                            <Check className="h-3.5 w-3.5" /> Copied
                          </>
                        ) : (
                          <>
                            <Copy className="h-3.5 w-3.5" /> Copy
                          </>
                        )}
                      </button>
                      <button
                        onClick={() => handleResend(invitation)}
                        title="Re-send invite email"
                        className="flex items-center gap-1.5 rounded-md border-2 border-black px-3 py-1.5 text-xs font-bold uppercase tracking-wider hover:bg-pop-yellow/20"
                      >
                        <Send className="h-3.5 w-3.5" /> Resend
                      </button>
                    </>
                  )}
                  <button
                    onClick={() => handleRevoke(invitation)}
                    title="Revoke invite"
                    className="flex items-center justify-center rounded-md border-2 border-pop-red px-2.5 py-1.5 text-pop-red hover:bg-pop-red/10"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
