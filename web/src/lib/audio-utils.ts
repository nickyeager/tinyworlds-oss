/**
 * Audio utility functions for handling browser audio formats.
 *
 * Different browsers use different audio formats:
 * - Chrome: audio/webm, audio/webm;codecs=opus
 * - Firefox: audio/ogg, audio/ogg;codecs=opus
 * - Safari: audio/mp4, audio/mp4;codecs=mp4a.40.2
 *
 * When MediaRecorder.mimeType is empty (can happen due to timing or browser quirks),
 * we default to "webm" as it's the most common browser format.
 */

/**
 * Get the file extension for an audio blob based on its MIME type.
 *
 * @param blobType - The MIME type of the audio blob (e.g., "audio/webm", "audio/ogg")
 * @returns The appropriate file extension ("webm", "ogg", or "mp4")
 *
 * @example
 * getAudioExtension("audio/webm") // "webm"
 * getAudioExtension("audio/webm;codecs=opus") // "webm"
 * getAudioExtension("audio/ogg;codecs=opus") // "ogg"
 * getAudioExtension("audio/mp4") // "mp4"
 * getAudioExtension("") // "webm" (safe default)
 */
export function getAudioExtension(blobType: string): string {
  // Default to webm (most common browser format) when type is empty or unknown
  if (blobType.includes("ogg")) {
    return "ogg";
  }
  if (blobType.includes("mp4") || blobType.includes("m4a")) {
    return "mp4";
  }
  // Default to webm for empty, unknown, or webm types
  return "webm";
}

/**
 * Ensure an audio blob has a proper MIME type set.
 *
 * When MediaRecorder.mimeType is empty (can happen due to timing or browser quirks),
 * the blob will have an empty type. This causes issues when sending via FormData
 * because the browser won't set the correct Content-Type header.
 *
 * This function creates a new blob with the correct MIME type if needed.
 *
 * @param blob - The original audio blob
 * @returns A blob with the correct MIME type set
 */
export function ensureAudioBlobType(blob: Blob): Blob {
  // If blob already has a type, return it as-is
  if (blob.type) {
    return blob;
  }

  // Create a new blob with the correct MIME type (default to webm)
  // We use audio/webm because Chrome (most common browser) uses webm
  return new Blob([blob], { type: "audio/webm" });
}
