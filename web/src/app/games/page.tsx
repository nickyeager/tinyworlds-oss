"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import {
  listAllGames,
  getScreenshotUrl,
  type UnifiedGameInfo,
} from "@/lib/api";
import { Plus, Loader2 } from "lucide-react";
import { useAuth } from "@/hooks/use-auth";
import { SiteNav } from "@/components/site-nav";
import { DeleteGameButton } from "@/components/delete-game-button";

export default function GamesPage() {
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const [games, setGames] = useState<UnifiedGameInfo[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (authLoading) return;
    listAllGames()
      .then(setGames)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [authLoading, isAuthenticated]);

  return (
    <div className="flex min-h-screen flex-col bg-surface text-txt-primary selection:bg-pop-yellow/30">
      <SiteNav>
        <Link
          href="/create"
          aria-label="Make a game"
          className="flex items-center gap-1.5 rounded-md bg-pop-yellow px-3 sm:px-4 py-2 text-sm font-bold uppercase tracking-wider text-surface brutal-border transition-colors hover:bg-pop-lime"
        >
          <Plus className="h-4 w-4" />
          <span className="hidden sm:inline">Make a game</span>
        </Link>
      </SiteNav>

      <main className="flex flex-1 flex-col px-4 sm:px-8 pb-16">
        <h1 className="mb-8 font-[family-name:var(--font-heading)] text-4xl font-bold">
          Games
        </h1>

        {loading ? (
          <div className="flex flex-1 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-pop-yellow" />
          </div>
        ) : games.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-4">
            <p className="font-mono text-sm font-bold text-txt-muted">
              No games yet.
            </p>
            <Link
              href="/create"
              className="rounded-md bg-pop-yellow px-5 py-2 text-sm font-bold uppercase tracking-wider text-surface brutal-border transition-colors hover:bg-pop-lime"
            >
              Make a game
            </Link>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6 gap-4 sm:gap-5">
            {games.map((game) => (
              <Link
                key={game.game_id}
                href={`/games/${game.game_id}`}
                className="group rounded-lg bg-surface-raised brutal-card overflow-hidden brutal-chip"
              >
                <div className="relative aspect-[4/3] bg-surface border-b-2 border-[var(--card-border)]">
                  {game.has_export || game.has_video ? (
                    <img
                      src={getScreenshotUrl(game.engine, game.game_id)}
                      alt=""
                      className="h-full w-full object-cover opacity-70 group-hover:opacity-100 transition-opacity"
                      onError={(e) => {
                        (e.target as HTMLImageElement).style.display = "none";
                      }}
                    />
                  ) : (
                    <div className="flex h-full items-center justify-center">
                      <span className="font-mono text-xs font-bold text-txt-muted">
                        No picture yet
                      </span>
                    </div>
                  )}
                  {/* Delete button — opacity-0 until card hover so it doesn't
                      clutter the grid. Stop propagation so clicking it doesn't
                      navigate into the game. */}
                  {game.can_edit && <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <DeleteGameButton
                      engine={game.engine}
                      gameId={game.game_id}
                      variant="icon"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                      }}
                      onDeleted={() =>
                        setGames((prev) =>
                          prev.filter((g) => g.game_id !== game.game_id)
                        )
                      }
                    />
                  </div>}
                </div>
                <div className="px-3 py-2 flex items-center justify-between gap-2">
                  <span className="text-sm font-bold truncate" title={game.game_id}>
                    {game.name || game.game_id}
                  </span>
                  {!game.has_export && (
                    <span className="tag shrink-0 bg-surface-overlay text-txt-muted">Not ready</span>
                  )}
                </div>
              </Link>
            ))}
          </div>
        )}
      </main>

    </div>
  );
}
