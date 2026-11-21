import type { Metadata } from "next";

type Engine = "godot" | "bevy";

type GameInfo = {
  game_id: string;
  name?: string | null;
  has_export?: boolean;
  has_video?: boolean;
  engine?: Engine;
};

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://tinyworlds.us";
const API_BASE = process.env.NEXT_PUBLIC_API_URL || SITE_URL;
const SITE_NAME = "TinyWorlds";

function resolveEngine(gameId: string): Engine {
  return gameId.startsWith("bevy-") ? "bevy" : "godot";
}

function absoluteUrl(path: string): string {
  return new URL(path, SITE_URL).toString();
}

async function fetchGameInfo(gameId: string): Promise<GameInfo | null> {
  const engine = resolveEngine(gameId);
  try {
    const response = await fetch(`${API_BASE}/api/v1/${engine}/games/${gameId}`, {
      // Game names and screenshots can change after edits. Keep share
      // previews fresh without making every request fully dynamic.
      next: { revalidate: 300 },
    });
    if (!response.ok) return null;
    return response.json();
  } catch {
    return null;
  }
}

type GameLayoutProps = {
  children: React.ReactNode;
  params: Promise<{ id: string }>;
};

export async function generateMetadata({
  params,
}: Omit<GameLayoutProps, "children">): Promise<Metadata> {
  const { id: gameId } = await params;
  const game = await fetchGameInfo(gameId);
  const engine = game?.engine ?? resolveEngine(gameId);
  const title = game?.name?.trim() || "TinyWorlds game";
  const url = absoluteUrl(`/games/${gameId}`);
  const imageUrl = `${API_BASE}/api/v1/${engine}/games/${gameId}/screenshot`;
  const description = game?.has_export
    ? `Play ${title}, a game made with TinyWorlds.`
    : `${title} is a game made with TinyWorlds.`;

  return {
    title,
    description,
    alternates: { canonical: url },
    openGraph: {
      type: "website",
      siteName: SITE_NAME,
      title: `${title} · ${SITE_NAME}`,
      description,
      url,
      images: [
        {
          url: imageUrl,
          width: 1200,
          height: 630,
          alt: `A picture of ${title}`,
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title: `${title} · ${SITE_NAME}`,
      description,
      images: [imageUrl],
    },
  };
}

export default function GameLayout({ children }: GameLayoutProps) {
  return children;
}
