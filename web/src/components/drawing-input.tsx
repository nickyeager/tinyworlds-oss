"use client";

import { useCallback, useEffect, useRef, useState, type PointerEvent } from "react";
import { Camera, ImagePlus, Pencil, Undo2 } from "lucide-react";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { withReferencePurpose, type ReferencePurpose } from "@/lib/visual-reference";

type Point = { x: number; y: number };
type Stroke = { points: Point[]; circle: boolean };
const WIDTH = 1024, HEIGHT = 768;

export function DrawingInput({ onAttach, imageSource }: { onAttach: (file: File) => void; imageSource?: string }) {
  const [open, setOpen] = useState(false);
  const [count, setCount] = useState(0);
  const [purpose, setPurpose] = useState<ReferencePurpose>(imageSource ? "annotation" : "idea");
  const [hasPicture, setHasPicture] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(false);
  const canvas = useRef<HTMLCanvasElement>(null);
  const background = useRef<HTMLCanvasElement | null>(null);
  const upload = useRef<HTMLInputElement>(null);
  const camera = useRef<HTMLInputElement>(null);
  const strokes = useRef<Stroke[]>([]);
  const active = useRef<number | null>(null);
  const imageVersion = useRef(0);

  const redraw = useCallback(() => {
    const ctx = canvas.current?.getContext("2d");
    if (!ctx) return;
    ctx.fillStyle = "white"; ctx.fillRect(0, 0, WIDTH, HEIGHT);
    if (background.current) ctx.drawImage(background.current, 0, 0);
    ctx.lineWidth = 7; ctx.lineCap = "round"; ctx.lineJoin = "round";
    for (const { points, circle } of strokes.current) {
      if (!points.length) continue;
      ctx.strokeStyle = circle ? "#ed367c" : "#171717"; ctx.fillStyle = ctx.strokeStyle;
      ctx.beginPath();
      if (circle && points.length > 1) {
        const a = points[0], b = points[points.length - 1];
        ctx.ellipse((a.x + b.x) / 2, (a.y + b.y) / 2, Math.max(3, Math.abs(a.x - b.x) / 2), Math.max(3, Math.abs(a.y - b.y) / 2), 0, 0, Math.PI * 2);
      } else {
        ctx.moveTo(points[0].x, points[0].y);
        for (const p of points.slice(1)) ctx.lineTo(p.x, p.y);
      }
      ctx.stroke();
      if (points.length === 1) { ctx.beginPath(); ctx.arc(points[0].x, points[0].y, 3.5, 0, Math.PI * 2); ctx.fill(); }
    }
  }, []);

  const loadPicture = useCallback(async (file: Blob, version: number, signal?: AbortSignal) => {
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type) || file.size > 10 * 1024 * 1024) throw new Error("Pick a PNG, JPG or WebP picture under 10 MB.");
    const bitmap = await createImageBitmap(file);
    try {
      if (bitmap.width * bitmap.height > 16_000_000) throw new Error("Pick a smaller picture, under 16 megapixels.");
      if (signal?.aborted || imageVersion.current !== version) return;
      const base = document.createElement("canvas"); base.width = WIDTH; base.height = HEIGHT;
      const ctx = base.getContext("2d"); if (!ctx) throw new Error("We couldn’t open this picture.");
      ctx.fillStyle = "white"; ctx.fillRect(0, 0, WIDTH, HEIGHT);
      const scale = Math.min(WIDTH / bitmap.width, HEIGHT / bitmap.height);
      ctx.drawImage(bitmap, (WIDTH - bitmap.width * scale) / 2, (HEIGHT - bitmap.height * scale) / 2, bitmap.width * scale, bitmap.height * scale);
      background.current = base; strokes.current = []; setCount(0); setHasPicture(true); redraw();
    } finally { bitmap.close(); }
  }, [redraw]);

  useEffect(() => {
    if (!open) return;
    const frame = requestAnimationFrame(redraw);
    if (!imageSource) return () => cancelAnimationFrame(frame);
    const controller = new AbortController();
    const version = ++imageVersion.current;
    setLoading(true); setError(null);
    void fetch(imageSource, { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error("We couldn’t load that screenshot. Try again.");
      await loadPicture(await response.blob(), version, controller.signal);
    }).catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "We couldn’t load that screenshot."); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { cancelAnimationFrame(frame); controller.abort(); };
  }, [open, imageSource, redraw, loadPicture]);

  function point(event: PointerEvent<HTMLCanvasElement>): Point {
    const box = event.currentTarget.getBoundingClientRect();
    return { x: Math.max(0, Math.min(WIDTH, (event.clientX - box.left) * WIDTH / box.width)), y: Math.max(0, Math.min(HEIGHT, (event.clientY - box.top) * HEIGHT / box.height)) };
  }
  async function addPicture(file?: File) {
    if (!file) return;
    const version = ++imageVersion.current;
    setLoading(true); setError(null);
    try { await loadPicture(file, version); }
    catch (e) { setError(e instanceof Error ? e.message : "We couldn’t open that picture."); }
    finally { if (imageVersion.current === version) setLoading(false); }
  }
  async function attachDrawing() {
    if (!canvas.current || (!strokes.current.length && !hasPicture) || saving || loading) return;
    setSaving(true);
    try {
      const blob = await new Promise<Blob | null>(resolve => canvas.current!.toBlob(resolve, "image/png"));
      if (!blob) throw new Error("No drawing data");
      const filename = purpose === "annotation" ? "marked-screenshot.png" : purpose === "level" ? "my-level.png" : purpose === "character" ? "my-character.png" : "my-drawing.png";
      onAttach(withReferencePurpose(new File([blob], filename, { type: "image/png" }), purpose)); setOpen(false); setError(null);
    } catch { setError("We couldn’t save your drawing. Try again."); }
    finally { setSaving(false); }
  }
  return <>
    <button type="button" onClick={() => setOpen(true)} className="inline-flex min-h-10 items-center gap-2 rounded-lg px-2 text-sm text-txt-secondary hover:bg-white/5 hover:text-txt-primary" aria-label={imageSource ? "Mark this screenshot" : "Add a drawing or photo"}><Pencil className="size-4" />{imageSource ? "Mark a change" : "Add a drawing"}</button>
    <Dialog open={open} onOpenChange={value => { setOpen(value); if (!value) { imageVersion.current++; setLoading(false); active.current = null; } }}><DialogContent className="max-h-[95dvh] overflow-auto sm:max-w-2xl">
      <DialogTitle>{imageSource ? "Circle what to change" : "Draw your idea"}</DialogTitle>
      <DialogDescription>{purpose === "annotation" ? "Drag to circle a part. You can explain the change before sending." : purpose === "level" ? "Draw paths, platforms and obstacles. We’ll turn your map into a playable level." : purpose === "character" ? "Draw one character on plain white paper. We’ll cut it out and bring it into your game." : "Draw here, or add a photo of a drawing."}</DialogDescription>
      {!imageSource && <div role="group" aria-label="Use this picture as" className="flex gap-2">{([ ["idea", "An idea"], ["level", "A level"], ["character", "A character"] ] as const).map(([value, label]) => <button key={value} type="button" aria-pressed={purpose === value} onClick={() => setPurpose(value)} className={`min-h-11 flex-1 rounded-lg px-2 text-sm ${purpose === value ? "bg-pop-yellow text-surface font-bold" : "bg-white/5 text-txt-secondary"}`}>{label}</button>)}</div>}
      <div className="relative overflow-hidden rounded-xl border-2 border-[var(--card-border)] bg-white">
        <canvas ref={canvas} aria-busy={loading} aria-disabled={loading || saving} width={WIDTH} height={HEIGHT} aria-label={imageSource ? "Circle the part to change" : "Draw your idea here"} className="block aspect-[4/3] w-full touch-none" onPointerDown={e => {
          if (active.current !== null || e.button !== 0 || loading || saving) return;
          active.current = e.pointerId; e.currentTarget.setPointerCapture(e.pointerId);
          strokes.current.push({ points: [point(e)], circle: purpose === "annotation" }); setCount(strokes.current.length); redraw();
        }} onPointerMove={e => {
          if (active.current !== e.pointerId) return;
          const stroke = strokes.current[strokes.current.length - 1];
          const next = point(e), previous = stroke.points[stroke.points.length - 1];
          if (stroke.points.length >= 10000 || Math.hypot(next.x - previous.x, next.y - previous.y) < 0.5) return;
          if (stroke.circle) { stroke.points = [stroke.points[0], next]; redraw(); }
          else { stroke.points.push(next); const ctx = e.currentTarget.getContext("2d"); if (ctx) { ctx.beginPath(); ctx.moveTo(previous.x, previous.y); ctx.lineTo(next.x, next.y); ctx.stroke(); } }
        }} onPointerUp={() => { active.current = null; }} onPointerCancel={() => { active.current = null; }} onLostPointerCapture={() => { active.current = null; }} />
        {!count && !hasPicture && <p className="pointer-events-none absolute inset-0 flex items-center justify-center px-6 text-center text-lg text-neutral-400">{loading ? "Opening your picture…" : "Draw a hero, a level or a whole world."}</p>}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button type="button" disabled={!count || saving || loading} onClick={() => { strokes.current.pop(); setCount(strokes.current.length); redraw(); }} className="inline-flex min-h-11 items-center gap-2 px-2 text-sm disabled:opacity-30"><Undo2 className="size-4" />Undo</button>
        {!imageSource && <div className="flex gap-2"><button type="button" disabled={loading || saving} onClick={() => camera.current?.click()} className="inline-flex min-h-11 items-center gap-2 px-2 text-sm"><Camera className="size-4" />Take a photo</button><button type="button" disabled={loading || saving} onClick={() => upload.current?.click()} className="inline-flex min-h-11 items-center gap-2 px-2 text-sm"><ImagePlus className="size-4" />Add a picture</button></div>}
      </div>
      <input ref={upload} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" aria-label="Add a picture from this device" onChange={e => { void addPicture(e.target.files?.[0]); e.target.value = ""; }} />
      <input ref={camera} type="file" accept="image/*" capture="environment" className="hidden" aria-label="Take a photo of a drawing" onChange={e => { void addPicture(e.target.files?.[0]); e.target.value = ""; }} />
      {error && <p role="alert" className="text-sm text-pop-red">{error}</p>}
      <button type="button" disabled={(!count && !hasPicture) || (purpose === "annotation" && !count) || saving || loading} onClick={() => void attachDrawing()} className="min-h-12 rounded-lg bg-pop-yellow px-5 font-bold text-surface disabled:opacity-30">{saving ? "Adding…" : purpose === "annotation" ? "Use this marked picture" : purpose === "level" ? "Use this level" : purpose === "character" ? "Use this character" : "Use this drawing"}</button>
    </DialogContent></Dialog>
  </>;
}
