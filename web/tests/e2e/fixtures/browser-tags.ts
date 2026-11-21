/**
 * Helpers for asserting that resource-fetching browser tags actually
 * loaded their content, not just that they appeared in the DOM with a
 * `src` attribute.
 *
 * **Why this file exists** (see memory: feedback_test_browser_tag_loaded.md):
 *
 * Native <img>, <audio>, <video>, <model-viewer>, <iframe> tags issue a
 * plain GET with cookies but **no Authorization header**. Any backend
 * asset endpoint that requires `Authorization: Bearer …` will 401 those
 * tag-driven fetches even when:
 *   - the JWT is valid and in localStorage
 *   - Playwright's `request.get(src, { headers: { Authorization } })`
 *     to the same URL returns 200
 *   - the element renders with the expected `src`
 *
 * The M3 demo run hit this exactly: <model-viewer> appeared with a
 * correct src, Playwright fetched 27 MB of glTF, but the UI was a blank
 * white canvas. Caught only because we captured screenshots. The
 * Bearer-only asset endpoint was the bug; the test gap was asserting
 * "element exists with src" instead of "element painted".
 *
 * Use one of these helpers anywhere a Playwright test renders a tag
 * that fetches a resource.
 */
import type { Page, Locator } from "@playwright/test";

/** Wait for the first <model-viewer> to report `loaded === true`. */
export async function waitForModelViewerLoaded(
  page: Page,
  options: { timeout?: number; selector?: string } = {},
): Promise<void> {
  const { timeout = 90_000, selector = "model-viewer" } = options;
  await page.waitForFunction(
    (sel: string) => {
      const mv = document.querySelector(sel) as
        | (Element & { loaded?: boolean; modelIsVisible?: boolean })
        | null;
      return !!mv && mv.loaded === true;
    },
    selector,
    { timeout },
  );
}

/**
 * Wait for the first <audio> / <video> element to be ready for playback
 * (readyState >= HAVE_FUTURE_DATA = 3).
 */
export async function waitForMediaReady(
  page: Page,
  options: { timeout?: number; selector?: string } = {},
): Promise<void> {
  const { timeout = 30_000, selector = "audio, video" } = options;
  await page.waitForFunction(
    (sel: string) => {
      const el = document.querySelector(sel) as
        | (HTMLMediaElement | null);
      return !!el && el.readyState >= 3;
    },
    selector,
    { timeout },
  );
}

/**
 * Wait for an <iframe> to fire its `load` event. NOTE: the load event
 * fires even when the iframe shows a 404 page — there's no cross-origin
 * way to tell whether the loaded document is the one we wanted. For
 * security-sensitive cases pair this with a network-capture: filter
 * `page.on("response")` for the iframe's URL and assert status 200.
 */
export async function waitForIframeLoaded(
  locator: Locator,
  options: { timeout?: number } = {},
): Promise<void> {
  const { timeout = 60_000 } = options;
  await locator.evaluate(
    (el: HTMLIFrameElement, t) =>
      new Promise<void>((resolve, reject) => {
        try {
          if (el.contentDocument?.readyState === "complete") {
            resolve();
            return;
          }
        } catch {
          // Cross-origin — contentDocument access throws. Fine: the
          // `error` event would still fire on a real network failure.
        }
        const timer = setTimeout(
          () => reject(new Error(`iframe ${el.src} not loaded within ${t}ms`)),
          t,
        );
        el.addEventListener("load", () => {
          clearTimeout(timer);
          resolve();
        });
        el.addEventListener("error", () => {
          clearTimeout(timer);
          reject(new Error(`iframe ${el.src} failed to load`));
        });
      }),
    timeout,
  );
}

/**
 * Wait for an <img> to finish loading. `complete` flips true on both
 * success and 404, so we also assert `naturalWidth > 0` — that's the
 * only way to distinguish a real load from a broken-image placeholder.
 */
export async function waitForImageLoaded(
  locator: Locator,
  options: { timeout?: number } = {},
): Promise<void> {
  const { timeout = 30_000 } = options;
  await locator.evaluate(
    (el: HTMLImageElement, t) =>
      new Promise<void>((resolve, reject) => {
        const timer = setTimeout(
          () => reject(new Error(`image not loaded within ${t}ms`)),
          t,
        );
        const check = () => {
          if (el.complete) {
            clearTimeout(timer);
            if (el.naturalWidth > 0) resolve();
            else reject(new Error(`image ${el.src} loaded but naturalWidth=0`));
          }
        };
        check();
        el.addEventListener("load", check);
        el.addEventListener("error", () =>
          reject(new Error(`image ${el.src} failed to load`)),
        );
      }),
    timeout,
  );
}
