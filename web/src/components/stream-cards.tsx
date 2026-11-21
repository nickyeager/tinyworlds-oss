"use client";

import { useState } from "react";
import type { StreamCard } from "@/lib/stream-cards";
import {
  FileCode,
  Terminal,
  Image,
  ClipboardList,
  Camera,
  Brain,
  AlertCircle,
  Info,
  ChevronDown,
  Eye,
  Film,
} from "lucide-react";

function CardWrapper({
  icon: Icon,
  iconColor,
  title,
  badge,
  badgeColor,
  children,
  defaultOpen = true,
  collapsible = false,
}: {
  icon: React.ComponentType<{ className?: string }>;
  iconColor: string;
  title: string;
  badge?: string;
  badgeColor?: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
  collapsible?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const headerClass = "flex w-full items-center gap-2 px-4 py-3 text-left border-b-2 border-[var(--card-border)]";
  const header = (
    <>
      <Icon className={`h-4 w-4 shrink-0 ${iconColor}`} />
      <span className="text-sm font-bold truncate flex-1">{title}</span>
      {badge && <span className={`tag ${badgeColor || "bg-surface-overlay text-txt-muted"}`}>{badge}</span>}
    </>
  );

  return (
    <div className="rounded-lg brutal-card bg-surface-raised overflow-hidden">
      {collapsible ? (
        <button
          type="button"
          aria-expanded={open}
          className={`${headerClass} cursor-pointer hover:bg-surface-overlay transition-colors`}
          onClick={() => setOpen(!open)}
        >
          {header}
          <ChevronDown className={`h-3 w-3 text-txt-muted transition-transform ${open ? "rotate-180" : ""}`} />
        </button>
      ) : (
        <div className={headerClass}>{header}</div>
      )}
      {open && <div>{children}</div>}
    </div>
  );
}

function FileCard({ card }: { card: StreamCard }) {
  const lines = (card.fileContent || "").split("\n");
  const isLong = lines.length > 15;
  const [expanded, setExpanded] = useState(false);
  const displayContent =
    isLong && !expanded
      ? lines.slice(0, 12).join("\n")
      : card.fileContent || "";
  const shortPath = card.filePath?.split("/").slice(-2).join("/") || "file";

  return (
    <CardWrapper
      icon={FileCode}
      iconColor="text-pop-cyan"
      title={shortPath}
      badge={card.fileAction === "created" ? "new" : "changed"}
      badgeColor={
        card.fileAction === "created"
          ? "bg-pop-lime text-surface"
          : "bg-pop-yellow text-surface"
      }
      collapsible
      defaultOpen={false}
    >
      <div className="relative">
        <div className="overflow-x-auto">
          <pre className="px-4 py-3 font-mono text-xs leading-relaxed text-txt-secondary overflow-x-auto">
            <code>{displayContent}</code>
          </pre>
        </div>
        {isLong && !expanded && (
          <button
            onClick={() => setExpanded(true)}
            className="w-full cursor-pointer border-t-2 border-[var(--card-border)] py-1.5 font-mono text-[10px] font-bold uppercase tracking-wider text-txt-muted hover:text-txt-secondary hover:bg-surface-overlay transition-colors"
          >
            Show all
          </button>
        )}
      </div>
    </CardWrapper>
  );
}

function CommandCard({ card }: { card: StreamCard }) {
  return (
    <CardWrapper
      icon={Terminal}
      iconColor="text-pop-lime"
      title={card.command?.slice(0, 60) || "Step"}
      collapsible
      defaultOpen={false}
    >
      <pre className="px-4 py-3 font-mono text-xs text-txt-muted leading-relaxed whitespace-pre-wrap break-all max-h-40 overflow-y-auto">
        {card.commandOutput || card.command}
      </pre>
    </CardWrapper>
  );
}

function AssetCard({ card }: { card: StreamCard }) {
  return (
    <CardWrapper
      icon={Image}
      iconColor="text-pop-pink"
      title={card.imageName || "Picture"}
    >
      {card.imageUrl ? (
        <div className="p-3">
          <img
            src={card.imageUrl}
            alt={card.imageName || "Picture"}
            className="max-h-48 rounded-md border-2 border-[var(--card-border)]"
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = "none";
            }}
          />
        </div>
      ) : (
        <div className="px-4 py-3 font-mono text-xs text-txt-muted">
          {card.command || "Making a picture…"}
        </div>
      )}
    </CardWrapper>
  );
}

function PlanCard({ card }: { card: StreamCard }) {
  const lines = (card.planContent || "").split("\n");
  const [expanded, setExpanded] = useState(false);
  const isLong = lines.length > 20;
  const displayContent =
    isLong && !expanded
      ? lines.slice(0, 15).join("\n")
      : card.planContent || "";

  return (
    <CardWrapper
      icon={ClipboardList}
      iconColor="text-pop-yellow"
      title="The plan"
    >
      <div className="px-4 py-3 font-mono text-sm text-txt-secondary leading-relaxed whitespace-pre-wrap">
        {displayContent}
        {isLong && !expanded && (
          <button
            onClick={() => setExpanded(true)}
            className="block w-full cursor-pointer mt-2 pt-2 border-t-2 border-[var(--card-border)] text-[10px] font-bold uppercase tracking-wider text-txt-muted hover:text-txt-secondary"
          >
            Show all
          </button>
        )}
      </div>
    </CardWrapper>
  );
}

function ScreenshotCard({ card }: { card: StreamCard }) {
  return (
    <CardWrapper
      icon={Camera}
      iconColor="text-pop-cyan"
      title={card.imageName || "Picture of your game"}
    >
      {card.imageUrl ? (
        <div className="p-3">
          <img
            src={card.imageUrl}
            alt="Picture of your game"
            className="w-full rounded-md border-2 border-[var(--card-border)]"
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = "none";
            }}
          />
        </div>
      ) : (
        <div className="px-4 py-3 font-mono text-xs text-txt-muted">
          Taking a picture…
        </div>
      )}
    </CardWrapper>
  );
}

function PreviewCard({ card }: { card: StreamCard }) {
  const isVideo = card.previewType === "video";
  return (
    <CardWrapper
      icon={isVideo ? Film : Eye}
      iconColor="text-pop-pink"
      title={card.previewName || (isVideo ? "Video" : "Picture")}
    >
      <div className="p-3">
        {isVideo ? (
          <video
            src={card.previewUrl}
            controls
            autoPlay
            muted
            className="w-full rounded-md border-2 border-[var(--card-border)]"
            style={{ maxHeight: "320px" }}
          />
        ) : (
          <img
            src={card.previewUrl}
            alt={card.previewName || "Picture"}
            className="w-full rounded-md border-2 border-[var(--card-border)]"
            style={{ maxHeight: "320px", objectFit: "contain" }}
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = "none";
            }}
          />
        )}
      </div>
    </CardWrapper>
  );
}

function ThinkingCard({ card }: { card: StreamCard }) {
  const text = card.thinkingText || "";
  const isLong = text.length > 150;
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="flex gap-2 px-2 py-1">
      <Brain className="h-3.5 w-3.5 shrink-0 text-txt-muted mt-0.5" />
      <p className="text-xs text-txt-muted italic leading-relaxed">
        {isLong && !expanded ? text.slice(0, 150) + "..." : text}
        {isLong && !expanded && (
          <button
            onClick={() => setExpanded(true)}
            className="ml-1 cursor-pointer text-txt-secondary hover:text-txt-primary underline"
          >
            more
          </button>
        )}
      </p>
    </div>
  );
}

function ErrorCard({ card }: { card: StreamCard }) {
  return (
    <div className="rounded-lg border-2 border-pop-red bg-pop-red/10 px-4 py-3 brutal-shadow-red">
      <div className="flex items-start gap-2">
        <AlertCircle className="h-4 w-4 shrink-0 text-pop-red mt-0.5" />
        <p className="text-sm font-bold text-pop-red leading-relaxed">
          {card.errorMessage}
        </p>
      </div>
    </div>
  );
}

function StatusCard({ card }: { card: StreamCard }) {
  if (card.details) {
    return (
      <details className="group rounded-lg border border-[var(--card-border)] bg-surface-raised px-3 py-2">
        <summary className="flex cursor-pointer list-none items-start gap-2 text-xs text-txt-secondary">
          <Info className="mt-0.5 size-3.5 shrink-0 text-txt-muted" />
          <span className="min-w-0 flex-1 break-words">{card.statusMessage}</span>
          <ChevronDown className="mt-0.5 size-3 shrink-0 text-txt-muted transition-transform group-open:rotate-180" />
        </summary>
        <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] leading-relaxed text-txt-secondary">{card.details}</pre>
      </details>
    );
  }
  return (
    <div className="flex items-center gap-2 px-2 py-1">
      <Info className="h-3.5 w-3.5 shrink-0 text-txt-muted" />
      <span className="font-mono text-xs text-txt-muted">{card.statusMessage}</span>
    </div>
  );
}

export function StreamCardView({ card }: { card: StreamCard }) {
  switch (card.type) {
    case "file":
      return <FileCard card={card} />;
    case "command":
      return <CommandCard card={card} />;
    case "asset":
      return <AssetCard card={card} />;
    case "plan":
      return <PlanCard card={card} />;
    case "screenshot":
      return <ScreenshotCard card={card} />;
    case "preview":
      return <PreviewCard card={card} />;
    case "thinking":
      return <ThinkingCard card={card} />;
    case "error":
      return <ErrorCard card={card} />;
    default:
      return <StatusCard card={card} />;
  }
}
