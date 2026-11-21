"use client";

import { useMemo, useSyncExternalStore, type SetStateAction } from "react";
import { readDraftImage, writeDraftImage } from "@/lib/editor-draft-images";
import { createClientId } from "@/lib/client-id";

interface Draft {
  text: string;
  image: File | null;
  missingReference: string | null;
}
interface DraftSnapshot extends Draft {
  ready: boolean;
  saved: boolean;
  notice: string;
  previous: Draft | null;
}
const emptyDraft: Draft = { text: "", image: null, missingReference: null };
const serverSnapshot: DraftSnapshot = { ...emptyDraft, ready: false, saved: false, notice: "", previous: null };

function createDraftStore(key: string) {
  let state: DraftSnapshot = { ...serverSnapshot, ready: true };
  const listeners = new Set<() => void>();
  let tabId = "storage-unavailable";
  try {
    tabId = sessionStorage.getItem("tinyworlds:editor-tab") || createClientId();
    sessionStorage.setItem("tinyworlds:editor-tab", tabId);
  } catch { /* Drafting also works with browser storage disabled. */ }
  const imageKey = `${key}:${tabId}`;
  let imageVersion = 0;
  let writes = Promise.resolve();
  try {
    state.text = sessionStorage.getItem(key) ?? "";
    state.missingReference = sessionStorage.getItem(`${key}:reference`);
    state.saved = true;
  } catch { /* Drafting works when storage is unavailable. */ }

  const update = (next: Partial<DraftSnapshot>) => {
    state = { ...state, ...next };
    try {
      if (state.text) sessionStorage.setItem(key, state.text);
      else sessionStorage.removeItem(key);
      const reference = state.image?.name ?? state.missingReference;
      if (reference) sessionStorage.setItem(`${key}:reference`, reference);
      else sessionStorage.removeItem(`${key}:reference`);
      state.saved = true;
    } catch { state.saved = false; }
    if ("image" in next) {
      imageVersion++;
      const image = state.image;
      writes = writes.then(() => writeDraftImage(imageKey, image)).catch(() => {
        if (state.image === image && image) {
          state = { ...state, notice: "We couldn't save your picture. Keep this tab open." };
          listeners.forEach((listener) => listener());
        }
      });
    }
    listeners.forEach((listener) => listener());
  };

  if (typeof indexedDB !== "undefined") {
    state.ready = false;
    void readDraftImage(imageKey).then((image) => {
      if (imageVersion === 0 && image) state = { ...state, image, missingReference: null };
    }).catch(() => { /* The filename remains available for recovery when storage fails. */ }).finally(() => {
      state = { ...state, ready: true };
      listeners.forEach((listener) => listener());
    });
  }

  return {
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
    getSnapshot: () => state,
    setText(value: SetStateAction<string>) {
      update({ text: typeof value === "function" ? value(state.text) : value, previous: null, notice: "" });
    },
    setImage(value: SetStateAction<File | null>) {
      update({ image: typeof value === "function" ? value(state.image) : value, missingReference: null, previous: null, notice: "" });
    },
    replace(text: string, options?: { image?: File; hasImage?: boolean; notice?: string }) {
      update({
        text, previous: { text: state.text, image: state.image, missingReference: state.missingReference },
        notice: options?.notice ?? "Idea added.",
        ...(options?.hasImage !== undefined ? {
          image: options.image ?? null,
          missingReference: options.hasImage && !options.image ? "The picture you sent before" : null,
        } : {}),
      });
    },
    undo() {
      if (state.previous) update({ ...state.previous, previous: null, notice: "Your words are back." });
    },
    clear() { update({ ...emptyDraft, previous: null, notice: "" }); },
  };
}

/** A tab-local draft with one recoverable replacement and persisted image bytes. */
export function useEditorDraft(key: string) {
  const store = useMemo(() => createDraftStore(key), [key]);
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot, () => serverSnapshot);
  return { ...state, canUndo: state.previous !== null, setText: store.setText, setImage: store.setImage, replace: store.replace, undo: store.undo, clear: store.clear };
}
