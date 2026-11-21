import { test, expect } from "@playwright/test";

// "/" has no page of its own: it sends every visitor to the create page.
// Idea chips and the picture budget are covered in game-editor.spec.ts.
test.describe("Home", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveURL(/\/create$/);
  });

  test("opens the create page", async ({ page }) => {
    await expect(
      page.getByRole("heading", { level: 1, name: "What game do you want to make?", exact: true })
    ).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Your game idea", exact: true })).toHaveValue("");

    const logo = page.getByRole("link", { name: "TinyWorlds", exact: true });
    await expect(logo).toBeVisible();
    await expect(logo).toHaveAttribute("href", "/create");
  });

  test("Make my game needs an idea first", async ({ page }) => {
    const idea = page.getByRole("textbox", { name: "Your game idea", exact: true });
    const make = page.getByRole("button", { name: "Make my game", exact: true });

    await expect(make).toBeDisabled();
    await idea.fill("   ");
    await expect(make).toBeDisabled();
    await idea.fill("A jumping frog game");
    await expect(make).toBeEnabled();
    await idea.fill("");
    await expect(make).toBeDisabled();
  });
});
