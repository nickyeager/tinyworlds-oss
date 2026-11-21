"use client";

import { useCallback, useEffect, useState } from "react";
import { getGameCreationLog, getModificationRunEvents, getModificationRuns, type Engine } from "@/lib/api";

type LoadState = "idle" | "loading" | "loaded" | "error";
type Result<T> = { key: string; status: "loaded" | "error"; data?: T; error?: string };

/** Loading is derived from the request identity, so old results cannot flash. */
function useHistoryRequest<T>(key: string, enabled: boolean, load: (signal: AbortSignal) => Promise<T>) {
  const [version, setVersion] = useState(0);
  const [result, setResult] = useState<Result<T> | null>(null);
  const identity = `${key}:${version}`;
  const current = result?.key === identity ? result : null;
  const hasResult = current !== null;
  useEffect(() => {
    if (!enabled || hasResult) return;
    const controller = new AbortController();
    void load(controller.signal).then(
      (data) => { if (!controller.signal.aborted) setResult({ key: identity, status: "loaded", data }); },
      (cause) => { if (!controller.signal.aborted) setResult({ key: identity, status: "error", error: cause instanceof Error ? cause.message : String(cause) }); },
    );
    return () => controller.abort();
  }, [enabled, hasResult, identity, load]);
  const refresh = useCallback(() => setVersion((value) => value + 1), []);
  return {
    data: enabled ? current?.data : undefined,
    error: enabled ? current?.error ?? null : null,
    status: (!enabled ? "idle" : current?.status ?? "loading") as LoadState,
    refresh, version,
  };
}

export function useGameHistory({ engine, gameId, ownerKey, canEdit, activeTab, requestedRunId }: {
  engine: Engine; gameId: string; ownerKey: string; canEdit: boolean; activeTab: string; requestedRunId: string | null;
}) {
  const key = `${ownerKey}/${engine}/${gameId}`;
  const loadCreation = useCallback((signal: AbortSignal) => getGameCreationLog(engine, gameId, signal), [engine, gameId]);
  const loadRuns = useCallback((signal: AbortSignal) => getModificationRuns(engine, gameId, signal), [engine, gameId]);
  const creation = useHistoryRequest(key, canEdit && activeTab === "buildlog", loadCreation);
  const modifications = useHistoryRequest(key, canEdit, loadRuns);
  const runs = modifications.data?.runs;
  const selectedRunId = runs?.some((run) => run.run_id === requestedRunId) ? requestedRunId : runs?.[0]?.run_id ?? null;
  const loadDetail = useCallback((signal: AbortSignal) => getModificationRunEvents(engine, gameId, selectedRunId!, signal), [engine, gameId, selectedRunId]);
  const detail = useHistoryRequest(`${key}/${selectedRunId}/${modifications.version}`, canEdit && activeTab === "modifications" && selectedRunId !== null, loadDetail);
  return { creation, modifications, detail, selectedRunId };
}
