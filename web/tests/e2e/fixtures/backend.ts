import { test as base, APIRequestContext } from "@playwright/test";

/**
 * Backend API configuration for E2E tests.
 * The webServer config in playwright.config.ts handles starting the backend.
 * This fixture provides typed access to the backend URL.
 */
export const BACKEND_URL = "http://localhost:8001";
export const API_PREFIX = "/api/v1";

/**
 * Helper to construct backend API URLs.
 */
export function apiUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${BACKEND_URL}${API_PREFIX}${normalizedPath}`;
}

/**
 * Wait for backend to be healthy.
 * Useful if you need to check backend availability within a test.
 */
export async function waitForBackend(
  request: APIRequestContext,
  timeout = 10000
): Promise<boolean> {
  const startTime = Date.now();
  while (Date.now() - startTime < timeout) {
    try {
      const response = await request.get(`${BACKEND_URL}/health`);
      if (response.ok()) {
        return true;
      }
    } catch {
      // Backend not ready yet
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return false;
}

/**
 * Extended test fixture that includes an API request context
 * pre-configured for the backend.
 */
export const test = base.extend<{
  apiContext: APIRequestContext;
}>({
  apiContext: async ({ playwright }, use) => {
    const apiContext = await playwright.request.newContext({
      baseURL: BACKEND_URL,
    });
    await use(apiContext);
    await apiContext.dispose();
  },
});

export { expect } from "@playwright/test";
