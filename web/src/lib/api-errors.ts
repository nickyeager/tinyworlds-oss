/**
 * Coerce a FastAPI error payload into a human-readable single-line string.
 *
 * FastAPI's `detail` field can take **four** shapes that real callers will
 * encounter:
 *
 *   1. Plain string (HTTPException with a string detail) — the most common
 *      case. Just return it.
 *
 *   2. Array of validation errors (422 from Pydantic / request-body
 *      validation): `[{loc: ["body","email"], msg: "field required", type: "..."}]`.
 *      Each entry's `.msg` is the actually-useful bit; concatenate them
 *      with the (last) field name from `.loc` if present so the user knows
 *      WHICH field failed.
 *
 *   3. Object with its own .message / .detail (when our backend nests an
 *      error object): unwrap.
 *
 *   4. Missing entirely (response wasn't JSON, or didn't include `detail`):
 *      fall back to the caller-supplied label.
 *
 * The bug this exists to prevent: `throw new Error(error.detail)` where
 * `detail` is an array → JS coerces to `"[object Object]"` → user sees that
 * literal string in their error banner. Always call this helper instead.
 *
 * @param payload The parsed JSON body of a non-2xx response, OR null/undefined.
 * @param fallback Label to use when nothing useful can be extracted.
 */
export function formatApiError(
  payload: unknown,
  fallback: string,
): string {
  if (!payload || typeof payload !== "object") {
    return fallback;
  }

  const body = payload as Record<string, unknown>;
  const detail = body.detail;

  // Shape 1: plain string.
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }

  // Shape 2: array of Pydantic-style validation errors.
  if (Array.isArray(detail) && detail.length > 0) {
    const parts: string[] = [];
    for (const item of detail) {
      if (item && typeof item === "object") {
        const entry = item as Record<string, unknown>;
        const msg = typeof entry.msg === "string" ? entry.msg : null;
        const loc = Array.isArray(entry.loc) ? entry.loc : null;
        // Use the last segment of `loc` (the field name) for context.
        const field =
          loc && loc.length > 0
            ? String(loc[loc.length - 1])
            : null;
        if (msg && field && field !== "body") {
          parts.push(`${field}: ${msg}`);
        } else if (msg) {
          parts.push(msg);
        }
      } else if (typeof item === "string") {
        parts.push(item);
      }
    }
    if (parts.length > 0) return parts.join("; ");
  }

  // Shape 3: nested object with its own message/detail. Recurse one level.
  if (detail && typeof detail === "object") {
    const inner = detail as Record<string, unknown>;
    if (typeof inner.message === "string") return inner.message;
    if (typeof inner.detail === "string") return inner.detail;
  }

  // Some endpoints surface .message at the top level.
  if (typeof body.message === "string" && body.message.trim()) {
    return body.message;
  }

  return fallback;
}


/**
 * Convenience: fetch the body of a non-2xx Response and produce a clean
 * string. Use in catch blocks where you have the Response object but
 * haven't parsed it yet. Safe against non-JSON bodies (returns fallback).
 */
export async function readApiError(
  response: Response,
  fallback: string,
): Promise<string> {
  try {
    const body = await response.json();
    return formatApiError(body, fallback);
  } catch {
    // Non-JSON body (HTML error page, empty, etc.). Try text once; if
    // that also fails, just give the caller the fallback.
    try {
      const text = await response.text();
      return text.slice(0, 300) || fallback;
    } catch {
      return fallback;
    }
  }
}
