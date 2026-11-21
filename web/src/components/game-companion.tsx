"use client";

import { useEffect, useRef, useState, type RefObject } from "react";
import { API_BASE } from "@/lib/api-config";
import { getToken } from "@/lib/token-storage";

type Snapshot = { ready: boolean; actions: string[]; state: Record<string, unknown>; acknowledgement?: { id: string; accepted: boolean } | null };

/** Parent retains account credentials. The sandbox receives only bounded actions. */
export function GameCompanion({ gameId, playUrl, iframe, active }: { gameId: string; playUrl: string; iframe: RefObject<HTMLIFrameElement | null>; active: boolean }) {
  const [status, setStatus] = useState<"checking" | "local" | "external" | "legacy">("checking");
  const clientId = useRef<string | null>(null);
  useEffect(() => {
    if (!active) return;
    let alive = true, busy = false, lastContact = 0;
    let snapshot: Snapshot | null = null;
    const client = clientId.current ??= crypto.randomUUID().replaceAll("-", "");
    const origin = new URL(playUrl, location.href).origin;
    const send = (data: object) => iframe.current?.contentWindow?.postMessage(data, origin);
    const control = (external: boolean) => send({ type: "tinyworlds:pip:control", external });
    const listener = (event: MessageEvent) => {
      if (event.source !== iframe.current?.contentWindow || event.origin !== origin || event.data?.type !== "tinyworlds:pip") return;
      const data = event.data;
      if (data.ready === true && Array.isArray(data.actions) && data.actions.length > 0 && data.actions.length <= 64 && data.actions.every((a: unknown) => typeof a === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(a)) && data.state && typeof data.state === "object" && !Array.isArray(data.state)) {
        if (JSON.stringify(data.state).length > 16000) return;
        const firstObservation = snapshot === null;
        snapshot = { ready: true, actions: data.actions, state: data.state, acknowledgement: snapshot?.acknowledgement };
        if (!getToken()) setStatus("local");
        if (firstObservation) void tick();
      }
      const ack = data.ack ?? data.acknowledgement;
      if (snapshot && ack && typeof ack.id === "string" && ack.id.length <= 64 && typeof ack.accepted === "boolean") snapshot.acknowledgement = ack;
    };
    window.addEventListener("message", listener);
    const tick = async () => {
      send({ type: "tinyworlds:pip:observe" });
      if (Date.now() - lastContact > 4000) control(false);
      const token = getToken();
      if (!snapshot || busy || !token) return;
      busy = true;
      try {
        const response = await fetch(`${API_BASE}/api/v1/agent-play/games/${encodeURIComponent(gameId)}/sync`, {
          method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ client_id: client, actions: snapshot.actions, observation: snapshot.state, acknowledgement: snapshot.acknowledgement ?? null }),
          signal: AbortSignal.timeout(3500), cache: "no-store",
        });
        if (!response.ok) throw new Error("Companion unavailable");
        const state = await response.json();
        if (!alive) return;
        lastContact = Date.now();
        control(state.agent_connected === true);
        setStatus(state.agent_connected ? "external" : "local");
        if (state.command) send({ type: "tinyworlds:pip:action", command: state.command });
      } catch {
        if (alive) { control(false); setStatus("local"); }
      } finally { busy = false; }
    };
    void tick();
    const interval = setInterval(() => void tick(), 1000);
    const timeout = setTimeout(() => { if (!snapshot && alive) setStatus("legacy"); }, 10000);
    return () => { alive = false; clearInterval(interval); clearTimeout(timeout); window.removeEventListener("message", listener); control(false); };
  }, [active, gameId, iframe, playUrl]);
  if (!active) return null;
  return <span className="text-xs text-txt-muted">{status === "checking" ? "Looking for Pip…" : status === "legacy" ? "Pip can join after your next change" : status === "external" ? "Pip is playing · AI connected" : "Pip is playing"}</span>;
}
