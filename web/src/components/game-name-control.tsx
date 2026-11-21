"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, Pencil } from "lucide-react";
import { renameGame, type Engine, type GodotGameInfo } from "@/lib/api";
import { DeleteGameButton } from "./delete-game-button";

export function GameNameControl({ engine, game, canEdit, onRename, onDeleted }: {
  engine: Engine; game: GodotGameInfo; canEdit: boolean;
  onRename: (game: GodotGameInfo) => void; onDeleted: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const inFlight = useRef(false);
  const cancelled = useRef(false);
  useEffect(() => { if (editing) { input.current?.focus(); input.current?.select(); } }, [editing]);
  const cancel = () => { cancelled.current = true; setEditing(false); setError(null); };
  const submit = async () => {
    if (!canEdit || inFlight.current || cancelled.current) return;
    const trimmed = name.trim();
    if (!trimmed || trimmed === game.name) { cancel(); return; }
    inFlight.current = true; setSaving(true); setError(null);
    try {
      onRename(await renameGame(engine, game.game_id, trimmed));
      setEditing(false);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "We couldn't rename your game. Try again."); }
    finally { inFlight.current = false; setSaving(false); }
  };
  if (editing) return <div className="relative flex min-w-0 items-center gap-2">
    <input ref={input} type="text" value={name} onChange={(event) => setName(event.target.value)} onBlur={() => void submit()}
      onKeyDown={(event) => { if (event.key === "Enter") void submit(); else if (event.key === "Escape") cancel(); }}
      maxLength={80} disabled={saving} aria-label="Game name" aria-invalid={Boolean(error)} aria-describedby={error ? "game-rename-error" : undefined}
      className="min-w-0 w-40 sm:w-60 rounded border-2 border-pop-yellow bg-surface-raised px-2 py-1 text-sm font-bold text-txt-primary outline-none" />
    {saving && <Loader2 className="size-3.5 shrink-0 animate-spin text-pop-yellow" />}
    {error && <span id="game-rename-error" role="alert" className="absolute top-full z-30 mt-1 rounded bg-surface-raised p-2 text-xs text-pop-red">{error}</span>}
  </div>;
  return <div className="flex min-w-0 items-center gap-2">
    <span className="max-w-[100px] truncate font-[family-name:var(--font-heading)] text-sm font-bold text-txt-secondary sm:max-w-[240px]" title={game.game_id}>{game.name || game.game_id}</span>
    {canEdit && <>
      <button type="button" onClick={() => { cancelled.current = false; setName(game.name || ""); setError(null); setEditing(true); }} aria-label="Rename game" className="p-0.5 text-txt-muted transition-colors hover:text-pop-yellow"><Pencil className="size-3.5" /></button>
      <DeleteGameButton engine={engine} gameId={game.game_id} variant="icon" onDeleted={onDeleted} />
    </>}
  </div>;
}
