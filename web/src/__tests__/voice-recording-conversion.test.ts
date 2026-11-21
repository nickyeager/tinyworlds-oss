/**
 * Tests for the getAudioExtension utility function.
 *
 * This utility handles audio format detection for voice recordings,
 * correctly mapping browser MIME types to file extensions:
 * - Chrome: audio/webm, audio/webm;codecs=opus -> webm
 * - Firefox: audio/ogg, audio/ogg;codecs=opus -> ogg
 * - Safari: audio/mp4, audio/mp4;codecs=mp4a.40.2 -> mp4
 * - Empty/unknown: defaults to webm (most common format)
 */
import { describe, it, expect } from "vitest";
import { getAudioExtension, ensureAudioBlobType } from "../lib/audio-utils";

describe("getAudioExtension", () => {
  describe("standard browser formats", () => {
    it("returns webm for Chrome audio formats", () => {
      expect(getAudioExtension("audio/webm")).toBe("webm");
      expect(getAudioExtension("audio/webm;codecs=opus")).toBe("webm");
      expect(getAudioExtension("audio/webm;codecs=pcm")).toBe("webm");
    });

    it("returns ogg for Firefox audio formats", () => {
      expect(getAudioExtension("audio/ogg")).toBe("ogg");
      expect(getAudioExtension("audio/ogg;codecs=opus")).toBe("ogg");
    });

    it("returns mp4 for Safari audio formats", () => {
      expect(getAudioExtension("audio/mp4")).toBe("mp4");
      expect(getAudioExtension("audio/mp4;codecs=mp4a.40.2")).toBe("mp4");
      expect(getAudioExtension("audio/m4a")).toBe("mp4");
    });
  });

  describe("empty and unknown types", () => {
    /**
     * Empty blob.type can occur when MediaRecorder.mimeType is empty,
     * which happens due to timing issues or browser quirks.
     * Defaulting to webm prevents backend conversion failures since
     * most browsers (Chrome) use webm format.
     */
    it("defaults to webm when blob type is empty", () => {
      expect(getAudioExtension("")).toBe("webm");
    });

    it("does not return wav for empty type (regression test)", () => {
      // This was the original bug - empty types defaulted to wav
      // which caused backend conversion failures
      expect(getAudioExtension("")).not.toBe("wav");
    });

    it("defaults to webm for unknown audio types", () => {
      expect(getAudioExtension("audio/unknown")).toBe("webm");
      expect(getAudioExtension("application/octet-stream")).toBe("webm");
    });
  });

  describe("Blob API behavior", () => {
    it("Blob.type is empty string when created with empty or no type", () => {
      // This documents the browser behavior that triggers the empty-type edge case
      const blobEmptyType = new Blob(["test"], { type: "" });
      const blobNoType = new Blob(["test"]);

      expect(blobEmptyType.type).toBe("");
      expect(blobNoType.type).toBe("");
    });
  });
});

describe("ensureAudioBlobType", () => {
  it("returns the same blob if it already has a type", () => {
    const blob = new Blob(["test"], { type: "audio/webm" });
    const result = ensureAudioBlobType(blob);

    expect(result.type).toBe("audio/webm");
    // Should be the same blob instance since no conversion needed
    expect(result).toBe(blob);
  });

  it("creates a new blob with audio/webm type when original has empty type", () => {
    const blob = new Blob(["test audio data"], { type: "" });
    expect(blob.type).toBe(""); // Confirm original has empty type

    const result = ensureAudioBlobType(blob);

    expect(result.type).toBe("audio/webm");
    expect(result.size).toBe(blob.size); // Same data
    expect(result).not.toBe(blob); // New blob instance
  });

  it("creates a new blob with audio/webm type when original has no type", () => {
    const blob = new Blob(["test audio data"]);
    expect(blob.type).toBe(""); // No type specified

    const result = ensureAudioBlobType(blob);

    expect(result.type).toBe("audio/webm");
  });

  it("preserves ogg type if already set", () => {
    const blob = new Blob(["test"], { type: "audio/ogg" });
    const result = ensureAudioBlobType(blob);

    expect(result.type).toBe("audio/ogg");
    expect(result).toBe(blob);
  });

  it("preserves mp4 type if already set", () => {
    const blob = new Blob(["test"], { type: "audio/mp4" });
    const result = ensureAudioBlobType(blob);

    expect(result.type).toBe("audio/mp4");
    expect(result).toBe(blob);
  });
});
