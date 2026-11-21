"use client";

import { useMemo, type ReactNode } from "react";
import { AssistantRuntimeProvider, MessagePrimitive, ThreadPrimitive, useExternalStoreRuntime, type ThreadMessageLike } from "@assistant-ui/react";
import { ArrowDown, Paperclip, Pencil } from "lucide-react";
import { editorImageUrl, type EditTurn } from "@/lib/game-editor";
import type { Engine } from "@/lib/api";
import { EditorImage } from "./editor-image";

export function EditorConversation({ turns, engine, gameId, loading, busy, onSend, onCancel, onReuse, renderTurn, children }: {
  turns: EditTurn[]; engine: Engine; gameId: string; loading: boolean; busy: boolean;
  onSend: (text: string) => void; onCancel: () => Promise<void>;
  onReuse: (turn: EditTurn) => void; renderTurn: (turn: EditTurn) => ReactNode; children: ReactNode;
}) {
  const messages = useMemo<ThreadMessageLike[]>(() => turns.flatMap((turn) => [
    { id: `${turn.id}-request`, role: "user" as const, content: turn.instruction, metadata: { custom: { turn } } },
    { id: turn.id, role: "assistant" as const, content: turn.response || turn.events.at(-1)?.content || "Working on your game", status: turn.status === "running" ? { type: "running" as const } : { type: "complete" as const, reason: "stop" as const }, metadata: { custom: { turn } } },
  ]), [turns]);
  const runtime = useExternalStoreRuntime<ThreadMessageLike>({
    messages, convertMessage: (message) => message, isRunning: busy, isLoading: loading,
    onNew: async (message) => { onSend(message.content.filter((part) => part.type === "text").map((part) => part.text).join("\n")); },
    onCancel,
  });
  return <AssistantRuntimeProvider runtime={runtime}>
    <ThreadPrimitive.Root className="studio-conversation">
      <ThreadPrimitive.Viewport className="editor-scroll studio-transcript" role="log" aria-label="Your changes" turnAnchor="bottom" autoScroll={turns.length > 0} scrollToBottomOnRunStart scrollToBottomOnInitialize={turns.length > 0 && !loading}>
        {turns.length === 0 ? children : <ThreadPrimitive.Messages>{({ message }) => {
          const turn = message.metadata.custom.turn as EditTurn;
          if (!turn) return null;
          if (message.role !== "user") return <MessagePrimitive.Root className="studio-assistant-message">{renderTurn(turn)}</MessagePrimitive.Root>;
          const attachment = turn.attachments?.[0];
          const src = attachment ? editorImageUrl(engine, gameId, attachment.path) : turn.imageUrl;
          return <MessagePrimitive.Root className="studio-user-message">
            <div className="studio-request">
              {src && <EditorImage key={src} src={src} name={attachment?.name || turn.image?.name || "Picture"} label="Picture" alt="Your picture" />}
              {turn.hasImage && !src && <span className="studio-missing-image"><Paperclip size={13} /> Picture missing</span>}
              <p>{turn.instruction}</p>
            </div>
            <button type="button" className="studio-reuse" onClick={() => onReuse(turn)}><Pencil size={12} /> Use again</button>
          </MessagePrimitive.Root>;
        }}</ThreadPrimitive.Messages>}
      </ThreadPrimitive.Viewport>
      <ThreadPrimitive.ScrollToBottom aria-label="Jump to latest" className="studio-jump disabled:hidden" behavior="auto"><ArrowDown size={14} /> Jump to latest</ThreadPrimitive.ScrollToBottom>
    </ThreadPrimitive.Root>
  </AssistantRuntimeProvider>;
}
