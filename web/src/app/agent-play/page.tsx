"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowUp, ArrowDown, ArrowLeft, ArrowRight, Hourglass, Star, Loader2 } from "lucide-react";
import { SiteNav } from "@/components/site-nav";
import { useAuth } from "@/hooks/use-auth";
import { API_BASE } from "@/lib/api-config";
import { formatApiError } from "@/lib/api-errors";

type Action = "up" | "down" | "left" | "right" | "wait";
type ArenaState = {
  session_id: string; mode: "coop" | "versus"; controller: "builtin" | "external" | "auto";
  agent_name: string; agent_connected: boolean;
  positions: Record<"human" | "agent", [number, number]>;
  scores: Record<"human" | "agent", number>; target: [number, number];
  revision: number; turn: "human" | "agent" | null; outcome: "team" | "human" | "agent" | "tie" | "out-of-moves" | null;
  moves_remaining: number; legal_actions: Record<"human" | "agent", Action[]>;
};
const moves = [
  { action: "up", Icon: ArrowUp }, { action: "left", Icon: ArrowLeft },
  { action: "wait", Icon: Hourglass }, { action: "right", Icon: ArrowRight },
  { action: "down", Icon: ArrowDown },
] as const;
class ArenaError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

function PipArena() {
  const { ensureToken } = useAuth();
  const requested = useSearchParams().get("session");
  const router = useRouter();
  const [game, setGame] = useState<ArenaState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef(false);
  const board = useRef<HTMLDivElement>(null);
  const initial = useRef<{ key: string; promise: Promise<ArenaState> } | null>(null);
  const initialized = useRef<string | null>(null);

  const request = useCallback(async <T = ArenaState,>(path: string, options: RequestInit = {}): Promise<T> => {
    const token = await ensureToken();
    const response = await fetch(`${API_BASE}/api/v1/agent-play${path}`, {
      ...options, cache: "no-store",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    });
    if (!response.ok) throw new ArenaError(formatApiError(await response.json().catch(() => ({})), "Couldn’t reach Pip."), response.status);
    return response.status === 204 ? undefined as T : response.json();
  }, [ensureToken]);

  const connect = useCallback(async (body: object = {}) => request("/connect", { method: "POST", body: JSON.stringify(body) }), [request]);

  useEffect(() => { board.current?.focus({ preventScroll: true }); }, [game?.session_id]);

  useEffect(() => {
    let active = true;
    const key = requested ?? "current";
    if (!initial.current || initial.current.key !== key) {
      // Share bootstrap across Strict Mode effects and token initialization.
      // The server resumes atomically, so reconnects cannot create duplicates.
      const resume = async () => {
        try { return await connect(/^[a-f0-9]{32}$/.test(requested ?? "") ? { session_id: requested } : {}); }
        catch (e) {
          if (e instanceof ArenaError && e.status === 404) return connect();
          throw e;
        }
      };
      initial.current = { key, promise: resume() };
    }
    initial.current.promise.then((state) => {
      if (active && initialized.current !== key) { initialized.current = key; setGame(state); }
    }).catch((e) => { if (active && initialized.current !== key) setError(e.message); });
    return () => { active = false; };
  }, [requested, connect]);

  useEffect(() => {
    const id = game?.session_id;
    if (!id || game?.outcome) return;
    const interval = game?.turn === "agent" ? 600 : 2000;
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let failures = 0;
    async function poll() {
      try {
        const next = await request(`/${id}`, { signal: abort.signal });
        if (!abort.signal.aborted) {
          failures = 0;
          setError(null);
          setGame((current) => !current || current.session_id !== next.session_id || current.revision > next.revision ? current
            : current.revision === next.revision && current.agent_connected === next.agent_connected ? current : next);
        }
      } catch (e) {
        if (!abort.signal.aborted) {
          if (e instanceof ArenaError && e.status === 404) {
            try {
              const next = await connect();
              if (!abort.signal.aborted) { setGame(next); setError(null); }
            } catch { failures++; setError("Finding Pip again…"); }
          } else { failures++; setError("Finding Pip again…"); }
        }
      } finally {
        if (!abort.signal.aborted) timer = setTimeout(poll, Math.min(5000, interval * 2 ** failures));
      }
    }
    timer = setTimeout(poll, interval);
    return () => { abort.abort(); clearTimeout(timer); };
  }, [game?.session_id, game?.turn, game?.outcome, request, connect]);

  async function newRound(mode = game?.mode ?? "coop") {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError(null);
    try {
      const next = await connect({ mode, new_round: Boolean(game) });
      initialized.current = requested ?? "current";
      setGame(next);
      window.history.replaceState(null, "", "/agent-play");
    } catch (e) { setError(e instanceof Error ? e.message : "Couldn’t reach Pip."); }
    finally { pending.current = false; setBusy(false); }
  }

  async function move(action: Action) {
    if (!game || pending.current || !game.legal_actions.human.includes(action)) return;
    pending.current = true; setBusy(true); setError(null);
    try {
      setGame(await request(`/${game.session_id}/actions`, { method: "POST", body: JSON.stringify({ player: "human", action, expected_revision: game.revision }) }));
    } catch (e) {
      if (e instanceof ArenaError && e.status === 404) {
        try { setGame(await connect()); } catch { setError("Couldn’t reach Pip."); }
      } else {
        setError(e instanceof Error ? e.message : "That move didn’t work.");
        try { setGame(await request(`/${game.session_id}`)); } catch { /* Never replay a move. */ }
      }
    } finally { pending.current = false; setBusy(false); }
  }

  async function leave() {
    if (pending.current) return;
    pending.current = true;
    try { if (game) await request<void>(`/${game.session_id}`, { method: "DELETE" }); }
    catch { /* Leaving remains available when the connection has dropped. */ }
    finally { router.push("/create"); }
  }

  const status = !game ? "Getting Pip ready…" : game.outcome
    ? ({ team: "You and Pip won.", human: "You won.", agent: "Pip won this round.", tie: "It’s a tie.", "out-of-moves": "Out of moves. Try again?" }[game.outcome] ?? "Round finished")
    : game.turn === "agent" ? "Pip is thinking…" : "Your turn";

  return <div className="min-h-dvh bg-surface text-txt-primary">
    <SiteNav compact showAccount={false}><button onClick={() => void leave()} className="min-h-11 px-2 text-sm font-bold text-txt-secondary hover:text-pop-yellow cursor-pointer">Leave game</button></SiteNav>
    <main className="mx-auto max-w-xl px-4 pb-6 pt-4 sm:px-6">
      <header className="mb-5 flex items-start justify-between gap-3">
        <div><h1 className="font-[family-name:var(--font-heading)] text-3xl font-semibold">{game?.mode === "versus" ? "You vs Pip" : "You + Pip"}</h1>
          <p className="mt-1 text-sm text-txt-secondary">{game?.mode === "versus" ? "First to 3 stars wins." : "Collect 6 stars together."}</p></div>
        {game && <button disabled={busy} onClick={() => void newRound(game.mode === "coop" ? "versus" : "coop")} className="min-h-11 max-w-32 text-right text-sm font-bold text-pop-cyan hover:underline cursor-pointer disabled:opacity-40">{game.mode === "coop" ? "Play against Pip" : "Play together"}</button>}
      </header>
      {game ? <section aria-label="Dot Arena" onKeyDown={(e) => {
        if ((e.key === " " || e.key === "Enter") && e.target instanceof HTMLButtonElement) return;
        const action = ({ ArrowUp: "up", w: "up", ArrowDown: "down", s: "down", ArrowLeft: "left", a: "left", ArrowRight: "right", d: "right", " ": "wait" } as Record<string, Action>)[e.key];
        if (action) { e.preventDefault(); void move(action); }
      }}>
        <div className="mb-3 flex items-center justify-between text-sm font-bold"><span className="text-pop-yellow">You · {game.scores.human}</span><span className="text-pop-cyan">Pip · {game.scores.agent}</span></div>
        <div ref={board} tabIndex={0} aria-label="Game board. Use arrow keys or WASD to move." className="mx-auto aspect-square w-full max-w-[48dvh] rounded-xl border-2 border-[var(--card-border)] bg-surface-raised p-3 outline-none focus-visible:ring-2 focus-visible:ring-pop-yellow sm:max-w-[52dvh]">
          <svg viewBox="0 0 350 350" className="h-full w-full" aria-hidden="true">
            {Array.from({ length: 49 }, (_, i) => <rect key={i} x={(i % 7) * 50 + 2} y={Math.floor(i / 7) * 50 + 2} width="46" height="46" rx="8" fill="var(--background)" stroke="var(--card-border)" />)}
            <Star x={game.target[0] * 50 + 12} y={game.target[1] * 50 + 12} width="26" height="26" className="fill-pop-yellow text-pop-yellow" />
            {(["human", "agent"] as const).map((p) => <g key={p} transform={`translate(${game.positions[p][0] * 50 + 25} ${game.positions[p][1] * 50 + 25})`}>
              <rect x={p === "human" ? -17 : -12} y={p === "human" ? -17 : -12} width={p === "human" ? 34 : 24} height={p === "human" ? 34 : 24} rx={p === "human" ? 7 : 12} fill={p === "human" ? "#FFD166" : "#63D5EC"} stroke="#151922" strokeWidth="2" />
              <text textAnchor="middle" dy="5" fill="#151922" fontSize="13" fontWeight="800">{p === "human" ? "Y" : "P"}</text>
            </g>)}
          </svg>
        </div>
        <p role="status" className="mt-3 text-center font-bold">{status}</p>
        <p className="mt-1 text-center text-xs text-txt-secondary">{game.agent_connected ? "Pip · connected agent" : "Pip · local companion"}</p>
        {game.outcome ? <button disabled={busy} onClick={() => void newRound()} className="mx-auto mt-5 block min-h-12 rounded-lg bg-pop-yellow px-8 font-bold text-surface cursor-pointer">Play again</button>
          : <div className="mx-auto mt-4 flex justify-center gap-2" aria-label="Movement controls">{moves.map(({ action, Icon }) => <button key={action} aria-label={action === "wait" ? "Wait one turn" : `Move ${action}`} disabled={busy || !game.legal_actions.human.includes(action)} onClick={() => void move(action)} className="flex h-14 w-14 items-center justify-center rounded-lg border-2 border-[var(--card-border)] bg-surface-raised hover:border-pop-yellow focus-visible:ring-2 focus-visible:ring-pop-yellow cursor-pointer disabled:cursor-default disabled:opacity-30"><Icon size={22} /></button>)}</div>}
        <p className="mt-4 text-center text-xs text-txt-muted">Arrow keys or WASD · You are yellow, Pip is blue</p>
      </section> : <div className="flex aspect-square items-center justify-center gap-3 text-txt-secondary"><Loader2 className="size-5 animate-spin" /><p role="status">{status}</p></div>}
      {error && <div className="mt-4 text-center"><p role="alert" className="text-sm text-pop-red">{error}</p><button disabled={busy} onClick={() => void newRound()} className="mt-2 min-h-11 font-bold underline cursor-pointer">Try again</button></div>}
    </main>
  </div>;
}

function AccountArena() {
  const { user, isLoading } = useAuth();
  return isLoading ? <p className="p-8">Getting Pip ready…</p> : <PipArena key={user?.id ?? "guest"} />;
}

export default function AgentPlayPage() {
  return <Suspense fallback={<p className="p-8">Getting Pip ready…</p>}><AccountArena /></Suspense>;
}
