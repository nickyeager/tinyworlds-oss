"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Trash2 } from "lucide-react";
import { deleteGame, type Engine } from "@/lib/api";
import { getToken } from "@/lib/token-storage";

/**
 * Two-step delete confirmation. First click arms ("Tap again to delete"),
 * second click within 5 seconds executes the delete. After 5s of idle the
 * arm resets — gives the user an out without needing a modal.
 *
 * Variant controls visual density:
 *   - "icon": small icon-only button for cards / chips. Shows label only when armed.
 *   - "full": labeled button for detail pages. Always shows text.
 *
 * onDeleted runs after the API call succeeds — typically a router push or a
 * list refresh.
 */
export function DeleteGameButton({
  engine,
  gameId,
  variant = "icon",
  onDeleted,
  onClick,
}: {
  engine: Engine;
  gameId: string;
  variant?: "icon" | "full";
  onDeleted?: () => void;
  // Lets the parent run preventDefault/stopPropagation when this button is
  // inside an interactive ancestor (e.g. a <Link> card on the games list).
  onClick?: (e: React.MouseEvent) => void;
}) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Deletion requires an authenticated user. Track on mount to avoid SSR
  // mismatch — getToken() reads localStorage.
  const [canDelete, setCanDelete] = useState(false);
  const resetTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setCanDelete(getToken() !== null);
  }, []);

  useEffect(() => () => {
    if (resetTimer.current) clearTimeout(resetTimer.current);
  }, []);

  const handle = useCallback(
    async (e: React.MouseEvent) => {
      onClick?.(e);
      if (busy) return;
      if (!armed) {
        setArmed(true);
        setError(null);
        if (resetTimer.current) clearTimeout(resetTimer.current);
        resetTimer.current = setTimeout(() => setArmed(false), 5000);
        return;
      }
      // Armed → execute
      if (resetTimer.current) clearTimeout(resetTimer.current);
      setBusy(true);
      setError(null);
      try {
        await deleteGame(engine, gameId);
        onDeleted?.();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Couldn't delete. Try again.");
        setArmed(false);
      } finally {
        setBusy(false);
      }
    },
    [armed, busy, engine, gameId, onClick, onDeleted]
  );

  if (!canDelete) return null;

  if (variant === "icon") {
    return (
      <button
        type="button"
        onClick={handle}
        disabled={busy}
        title={armed ? "Tap again to delete" : "Delete game"}
        className={`flex items-center gap-1 rounded-md px-1.5 py-1 text-[10px] font-bold uppercase tracking-wider transition-colors brutal-border cursor-pointer ${
          armed
            ? "bg-pop-pink text-surface"
            : "bg-surface-overlay text-txt-muted hover:bg-pop-pink/20 hover:text-pop-pink"
        } disabled:opacity-50`}
        aria-label={armed ? "Tap again to delete" : "Delete game"}
      >
        <Trash2 className="h-3 w-3" />
        {armed && <span>Sure?</span>}
      </button>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        onClick={handle}
        disabled={busy}
        className={`flex items-center gap-2 rounded-md px-3 py-2 text-sm font-bold uppercase tracking-wider transition-colors brutal-border cursor-pointer ${
          armed
            ? "bg-pop-pink text-surface"
            : "bg-surface-overlay text-txt-muted hover:bg-pop-pink/20 hover:text-pop-pink"
        } disabled:opacity-50`}
      >
        <Trash2 className="h-4 w-4" />
        {busy ? "Deleting…" : armed ? "Tap again to delete" : "Delete game"}
      </button>
      {error && (
        <p className="text-xs text-pop-pink font-mono">{error}</p>
      )}
    </div>
  );
}
