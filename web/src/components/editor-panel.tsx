"use client";

import { useEffect, useState, type CSSProperties, type ReactNode } from "react";

export function EditorPanel({ children, className }: { children: ReactNode; className: string }) {
  const [width, setWidth] = useState(420);
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
    try {
      const saved = Number(localStorage.getItem("tinyworlds:studio-width"));
      if (saved >= 320 && saved <= 640) setWidth(saved);
    } catch { /* Use the default panel width without storage. */ }
    });
    return () => cancelAnimationFrame(frame);
  }, []);
  const resize = (next: number) => {
    const bounded = Math.round(Math.max(320, Math.min(640, window.innerWidth * 0.6, next)));
    setWidth(bounded);
    try { localStorage.setItem("tinyworlds:studio-width", String(bounded)); } catch { /* Resizing works without storage. */ }
  };
  return <section className={`studio-side-panel ${className}`} style={{ "--studio-chat-width": `${width}px` } as CSSProperties}>
    {children}
    <div role="separator" aria-label="Resize chat" aria-orientation="vertical" aria-valuemin={320} aria-valuemax={640} aria-valuenow={width} tabIndex={0} className="studio-panel-resizer"
      onKeyDown={(event) => { if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); resize(width + (event.key === "ArrowLeft" ? -24 : 24)); } }}
      onPointerDown={(event) => { event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId); }}
      onPointerMove={(event) => { if (event.currentTarget.hasPointerCapture(event.pointerId)) { const panel = event.currentTarget.parentElement!; resize(event.clientX - panel.getBoundingClientRect().left); } }}
      onPointerUp={(event) => { if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); }} />
  </section>;
}
