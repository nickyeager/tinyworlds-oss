/** Local UI identifiers also work on a phone's plain-HTTP LAN connection. */
let sequence = 0;

export function createClientId(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  if (globalThis.crypto?.getRandomValues) {
    return Array.from(globalThis.crypto.getRandomValues(new Uint8Array(16)), (byte) => byte.toString(16).padStart(2, "0")).join("");
  }
  return `local-${Date.now().toString(36)}-${(++sequence).toString(36)}`;
}
