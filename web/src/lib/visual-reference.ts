export type ReferencePurpose = "idea" | "level" | "character" | "annotation";
const purposes = new WeakMap<File, ReferencePurpose>();
export function referencePurpose(file: File): ReferencePurpose { return purposes.get(file) ?? "idea"; }
export function withReferencePurpose(file: File, purpose: ReferencePurpose): File { purposes.set(file, purpose); return file; }
export function referencePrompt(file: File, editing = true): string {
  switch (referencePurpose(file)) {
    case "level": return `${editing ? "Rebuild this game's level" : "Make a playable game"} from this drawn map. Match the paths, platforms and obstacles. Add a safe start and a reachable goal.`;
    case "character": return `${editing ? "Use" : "Make a game starring"} my drawn character as a playable sprite. Keep its shape and colors and animate it. ${editing ? "Keep the rest of the game working." : "Give it a simple adventure."}`;
    case "annotation": return "Change the part I marked in this screenshot. Keep everything else working.";
    default: return editing ? "Make my game look like this drawing. Keep how it plays." : "Make a fun game from this drawing. Use its characters, shapes and place.";
  }
}

export type VisualReference = { filename: string; content_type: string; data_base64: string; purpose?: ReferencePurpose };

export function encodeVisualReference(file: File, signal?: AbortSignal): Promise<VisualReference> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    const abort = () => { reader.abort(); reject(new DOMException("Cancelled", "AbortError")); };
    if (signal?.aborted) { abort(); return; }
    signal?.addEventListener("abort", abort, { once: true });
    reader.onloadend = () => signal?.removeEventListener("abort", abort);
    reader.onerror = () => reject(new Error("Could not read this image"));
    reader.onload = () => resolve({ purpose: referencePurpose(file), filename: file.name, content_type: file.type, data_base64: String(reader.result).split(",")[1] });
    reader.readAsDataURL(file);
  });
}
