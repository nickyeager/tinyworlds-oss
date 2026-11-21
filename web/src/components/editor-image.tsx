"use client";

/* eslint-disable @next/next/no-img-element -- Owner-authorized game assets and local blob previews. */
import { useState } from "react";
import { ImageOff, Maximize2, RotateCcw } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";

/** Reserve the thumbnail's size while decoding so image loads never shift history. */
export function EditorImage({ src, name, label = "Image", alt, compact = false }: { src: string; name: string; label?: string; alt?: string; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const url = attempt && !src.startsWith("blob:") ? `${src}${src.includes("?") ? "&" : "?"}retry=${attempt}` : src;
  return (
    <figure className={`studio-image${compact ? " studio-image--compact" : ""}`}>
      <div className="studio-image-frame">
        {failed ? <div className="studio-image-error" role="status"><ImageOff size={20} /><span>Picture didn’t load</span><button type="button" onClick={() => { setFailed(false); setLoaded(false); setAttempt((value) => value + 1); }}><RotateCcw size={12} /> Try again</button></div>
          : <button type="button" aria-label={`Open ${label.toLowerCase()}: ${name}`} onClick={() => setOpen(true)} className="studio-image-button">
            {!loaded && <span className="studio-image-loading" aria-label="Loading picture" />}
            <img key={url} src={url} alt={alt || name} onLoad={() => setLoaded(true)} onError={() => setFailed(true)} />
            <span className="studio-image-expand"><Maximize2 size={14} /></span>
          </button>}
      </div>
      <figcaption><span>{label}</span><span title={name}>{name}</span></figcaption>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="studio-image-dialog sm:max-w-[90vw]">
          <DialogTitle>{name}</DialogTitle>
          <DialogDescription className="sr-only">Full size {label.toLowerCase()}.</DialogDescription>
          <img src={url} alt={name} className="max-h-[78dvh] w-full object-contain" />
        </DialogContent>
      </Dialog>
    </figure>
  );
}
