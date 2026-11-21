import { API_BASE } from "./api-config";
import { readApiError } from "./api-errors";

export type Provider = "codex" | "claude";
export interface ProviderConnectionStatus {
  connection: { provider: Provider; kind: "existing_cli" | "managed"; model: string } | null;
  installed: Record<Provider, boolean>;
  pending_login: boolean;
}

export async function providerRequest<T>(path = "", method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}/api/v1/provider-connection${path}`, {
    method, cache: "no-store", credentials: "omit",
    headers: { "X-TinyWorlds-Local": "1", "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) throw new Error(await readApiError(response, "Could not update the provider connection."));
  return response.json();
}
