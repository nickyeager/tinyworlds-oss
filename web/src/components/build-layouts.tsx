"use client";

import { RefObject, useEffect, useRef, useState } from "react";
import { ArrowDown, Film, Image as ImageIcon } from "lucide-react";
import { StreamCard } from "@/lib/stream-cards";
import { StreamCardView } from "@/components/stream-cards";

export type BuildLayout = "two-pane";

interface LayoutProps {
  cards: StreamCard[];
  cardEndRef: RefObject<HTMLDivElement | null>;
}

interface MediaItem {
  key: string;
  url: string;
  name: string;
  type: "image" | "video";
}

/** Pick the latest media card per name so a re-captured screenshot replaces
 *  earlier copies of itself rather than stacking duplicates. */
function collectMedia(cards: StreamCard[]): MediaItem[] {
  const latest = new Map<string, MediaItem>();
  for (const c of cards) {
    if (c.type === "screenshot" && c.imageUrl) {
      latest.set(c.imageName || c.id, {
        key: c.imageName || c.id,
        url: c.imageUrl,
        name: c.imageName || "Screenshot",
        type: "image",
      });
    } else if (c.type === "preview" && c.previewUrl) {
      latest.set(c.previewName || c.id, {
        key: c.previewName || c.id,
        url: c.previewUrl,
        name: c.previewName || (c.previewType === "video" ? "Video" : "Image"),
        type: c.previewType === "video" ? "video" : "image",
      });
    }
  }
  return Array.from(latest.values());
}

function MediaTile({ item }: { item: MediaItem }) {
  const Icon = item.type === "video" ? Film : ImageIcon;
  return (
    <div className="rounded-lg brutal-card overflow-hidden bg-surface">
      <div className="flex items-center gap-2 px-3 py-1.5 border-b-2 border-[var(--card-border)] bg-surface-raised">
        <Icon className="h-3.5 w-3.5 text-pop-cyan shrink-0" />
        <span className="font-mono text-[11px] font-bold text-txt-secondary truncate">
          {item.name}
        </span>
      </div>
      <div className="bg-black/40">
        {item.type === "video" ? (
          <video
            src={item.url}
            controls
            muted
            playsInline
            className="w-full h-auto block"
          />
        ) : (
          <img
            src={item.url}
            alt={item.name}
            className="w-full h-auto block"
            onError={(e) => {
              (e.target as HTMLImageElement).style.opacity = "0.2";
            }}
          />
        )}
      </div>
    </div>
  );
}

function MediaGallery({ media }: { media: MediaItem[] }) {
  if (media.length === 0) {
    return (
      <div className="rounded-lg brutal-card bg-surface p-6 text-center">
        <ImageIcon className="h-6 w-6 text-txt-muted mx-auto mb-2" />
        <p className="font-mono text-xs text-txt-muted">
          Pictures of your game will show up here.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {media.map((m) => (
        <MediaTile key={m.key} item={m} />
      ))}
    </div>
  );
}

function CardsList({
  cards,
  cardEndRef,
  height,
}: LayoutProps & { height: string }) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const prevCountRef = useRef(cards.length);
  const [newCount, setNewCount] = useState(0);

  const scrollToBottom = () => {
    cardEndRef.current?.scrollIntoView({ behavior: "smooth" });
    setNewCount(0);
  };

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const away = el.scrollHeight - el.scrollTop - el.clientHeight > 80;
    if (!away) setNewCount(0);
  };

  useEffect(() => {
    const previous = prevCountRef.current;
    const delta = cards.length - previous;
    prevCountRef.current = cards.length;
    if (delta < 0) {
      queueMicrotask(() => setNewCount(0));
      return;
    }
    if (delta <= 0) return;
    setNewCount((count) => count + delta);
  }, [cards.length]);

  return (
    <div className="relative w-full rounded-lg brutal-card overflow-hidden bg-surface">
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className={`${height} overflow-y-auto p-3 space-y-2`}
      >
        {cards.map((card) => (
          <StreamCardView key={card.id} card={card} />
        ))}
        <div ref={cardEndRef} />
      </div>
      {newCount > 0 && (
        <button
          onClick={scrollToBottom}
          className="absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1.5 rounded-full border-2 border-[var(--card-border)] bg-surface-raised px-3 py-1.5 font-mono text-xs font-bold uppercase tracking-wider text-pop-yellow shadow-[3px_3px_0_#0a0a0a] transition-colors hover:text-pop-lime cursor-pointer"
        >
          <ArrowDown className="h-3.5 w-3.5" />
          {newCount} new
        </button>
      )}
    </div>
  );
}

/** Steps on the left, pictures on the right. */
function LayoutTwoPane(props: LayoutProps) {
  const media = collectMedia(props.cards);
  return (
    <div className="w-full grid grid-cols-1 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] gap-3">
      <CardsList {...props} height="h-[640px]" />
      <div className="rounded-lg brutal-card bg-surface-raised p-3 max-h-[640px] overflow-y-auto">
        <div className="flex items-center justify-between mb-3 sticky top-0 bg-surface-raised pb-2 border-b-2 border-[var(--card-border)] -mx-3 px-3 -mt-3 pt-3">
          <span className="font-mono text-xs font-bold uppercase tracking-wider text-txt-secondary">
            Pictures
          </span>
          <span className="font-mono text-[10px] font-bold text-txt-muted">
            {media.length}
          </span>
        </div>
        <MediaGallery media={media} />
      </div>
    </div>
  );
}

/** The build feed has one layout; the name is kept so callers stay unchanged. */
export function renderLayout(layout: BuildLayout, props: LayoutProps) {
  return <LayoutTwoPane key={layout} {...props} />;
}
