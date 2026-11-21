import { ImageResponse } from "next/og";

export const alt = "TinyWorlds — Make a game by describing it";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          background: "#0D0D0D",
          backgroundImage:
            "radial-gradient(circle at 20% 20%, rgba(255,219,88,0.15), transparent 45%), radial-gradient(circle at 80% 80%, rgba(78,205,196,0.12), transparent 45%)",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "72px 80px",
          fontFamily: "sans-serif",
          color: "#F5F5F5",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
          <div
            style={{
              width: 88,
              height: 88,
              background: "#FFDB58",
              borderRadius: 16,
              border: "4px solid #0D0D0D",
              boxShadow: "8px 8px 0 #4ECDC4",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="#0D0D0D" strokeWidth="2.5" strokeLinejoin="round">
              <path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z" />
              <path d="M3.27 6.96L12 12.01l8.73-5.05M12 22.08V12" />
            </svg>
          </div>
          <div style={{ fontSize: 56, fontWeight: 800, letterSpacing: -1 }}>TinyWorlds</div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ fontSize: 96, fontWeight: 800, lineHeight: 1.05, letterSpacing: -2 }}>
            Make a game
          </div>
          <div style={{ fontSize: 96, fontWeight: 800, lineHeight: 1.05, letterSpacing: -2, color: "#FFDB58" }}>
            by describing it
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ fontSize: 28, color: "#9A9A9A", fontFamily: "monospace" }}>
            tinyworlds.us
          </div>
          <div
            style={{
              padding: "12px 22px",
              background: "#FFDB58",
              color: "#0D0D0D",
              fontSize: 24,
              fontWeight: 800,
              borderRadius: 8,
              border: "3px solid #0D0D0D",
              boxShadow: "5px 5px 0 #0D0D0D",
              textTransform: "uppercase",
              letterSpacing: 2,
            }}
          >
            Make a game
          </div>
        </div>
      </div>
    ),
    { ...size },
  );
}
