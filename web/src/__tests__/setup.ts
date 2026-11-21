import { afterAll, afterEach, beforeAll } from "vitest";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import "@testing-library/jest-dom/vitest";

// Default handlers for common endpoints
export const handlers = [
  // Anonymous auth endpoint
  http.post("http://localhost:8001/api/v1/auth/anonymous", () => {
    return HttpResponse.json({
      access_token: "test-token-12345",
      token_type: "bearer",
    });
  }),
];

// Create MSW server
export const server = setupServer(...handlers);

// Start server before all tests
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));

// Reset handlers after each test
afterEach(() => server.resetHandlers());

// Close server after all tests
afterAll(() => server.close());
