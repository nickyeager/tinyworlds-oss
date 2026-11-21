import { afterEach, expect, it, vi } from "vitest";
import { createClientId } from "../client-id";

afterEach(() => vi.unstubAllGlobals());

it("creates distinct draft and turn IDs on HTTP LAN origins without randomUUID", () => {
  const getRandomValues = globalThis.crypto.getRandomValues.bind(globalThis.crypto);
  vi.stubGlobal("crypto", { getRandomValues });
  const ids = Array.from({ length: 32 }, createClientId);
  expect(ids.every((id) => typeof id === "string" && id.length > 0)).toBe(true);
  expect(new Set(ids).size).toBe(ids.length);
});

it("keeps local UI actions working when the browser has no crypto API", () => {
  vi.stubGlobal("crypto", undefined);
  expect(createClientId()).not.toBe(createClientId());
});
