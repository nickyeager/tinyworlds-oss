"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Link2 } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "./ui/dialog";

/** Native sharing on phones; manual copy remains available on HTTP LAN origins. */
export function ShareLinkButton({ url, title = "TinyWorlds game", label = "Share", native = true, className = "flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-xs text-txt-secondary transition-colors hover:bg-white/5" }: {
  url?: string; title?: string; label?: string; native?: boolean; className?: string;
}) {
  const [copied, setCopied] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [manualUrl, setManualUrl] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  const share = async () => {
    const link = new URL(url || window.location.href, window.location.href).href;
    setSharing(true);
    try {
      if (native && typeof navigator.share === "function") {
        try { await navigator.share({ title, url: link }); return; }
        catch (cause) { if (cause instanceof Error && cause.name === "AbortError") return; }
      }
      if (typeof navigator.clipboard?.writeText === "function") {
        try {
          await navigator.clipboard.writeText(link);
          setCopied(true);
          if (timer.current) clearTimeout(timer.current);
          timer.current = setTimeout(() => setCopied(false), 2000);
          return;
        } catch { /* Offer manual copy when permission is denied. */ }
      }
      setManualUrl(link);
    } finally { setSharing(false); }
  };
  return <>
    <button type="button" onClick={() => void share()} disabled={sharing} className={className}>
      {copied ? <><Check className="size-3.5 text-pop-lime" /><span className="text-pop-lime">Link copied</span></> : <><Link2 className="size-3.5" />{label}</>}
    </button>
    <Dialog open={manualUrl !== null} onOpenChange={(open) => { if (!open) setManualUrl(null); }}>
      <DialogContent>
        <DialogTitle>Share this game</DialogTitle>
        <DialogDescription>Copy this link to share your game.</DialogDescription>
        <input aria-label="Share link" readOnly value={manualUrl || ""} onFocus={(event) => event.currentTarget.select()} className="w-full rounded border border-white/20 bg-surface px-3 py-2 text-sm text-txt-primary" />
      </DialogContent>
    </Dialog>
  </>;
}
