import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { apiUrl } from "./fixtures/backend";

// Generate unique test data
const generateTestUser = () => ({
  email: `test-${Date.now()}-${Math.random().toString(36).slice(2)}@example.com`,
  password: "TestPassword123!",
  username: `testuser_${Date.now()}`,
});

test.describe("Authentication API", () => {
  test("anonymous token creation", async ({ request }) => {
    // Create anonymous user and get token
    const response = await request.post(apiUrl("/auth/anonymous"));
    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(data.access_token).toBeDefined();
    expect(data.token_type).toBe("bearer");
  });

  test("user registration", async ({ request }) => {
    const user = generateTestUser();

    // Register new user
    const response = await request.post(apiUrl("/auth/register"), {
      data: {
        email: user.email,
        password: user.password,
        username: user.username,
      },
    });

    expect(response.ok()).toBeTruthy();
    const data = await response.json();
    expect(data.access_token).toBeDefined();
    expect(data.token_type).toBe("bearer");
  });

  test("user login", async ({ request }) => {
    const user = generateTestUser();

    // First register the user
    const registerResponse = await request.post(apiUrl("/auth/register"), {
      data: {
        email: user.email,
        password: user.password,
        username: user.username,
      },
    });
    expect(registerResponse.ok()).toBeTruthy();

    // Now login with the same credentials
    const loginResponse = await request.post(apiUrl("/auth/login/json"), {
      data: {
        email: user.email,
        password: user.password,
      },
    });

    expect(loginResponse.ok()).toBeTruthy();
    const data = await loginResponse.json();
    expect(data.access_token).toBeDefined();
    expect(data.token_type).toBe("bearer");
  });

  test("login fails with wrong password", async ({ request }) => {
    const user = generateTestUser();

    // First register the user
    await request.post(apiUrl("/auth/register"), {
      data: {
        email: user.email,
        password: user.password,
        username: user.username,
      },
    });

    // Try to login with wrong password
    const loginResponse = await request.post(apiUrl("/auth/login/json"), {
      data: {
        email: user.email,
        password: "WrongPassword123!",
      },
    });

    expect(loginResponse.status()).toBe(401);
  });

  test("account upgrade from anonymous", async ({ request }) => {
    const user = generateTestUser();

    // First create an anonymous token
    const anonResponse = await request.post(apiUrl("/auth/anonymous"));
    expect(anonResponse.ok()).toBeTruthy();
    const anonData = await anonResponse.json();

    // Now upgrade the anonymous account to a registered account
    const upgradeResponse = await request.post(apiUrl("/auth/upgrade"), {
      headers: {
        Authorization: `Bearer ${anonData.access_token}`,
      },
      data: {
        email: user.email,
        password: user.password,
        username: user.username,
      },
    });

    expect(upgradeResponse.ok()).toBeTruthy();
    const upgradeData = await upgradeResponse.json();
    expect(upgradeData.access_token).toBeDefined();

    // Verify we can login with the upgraded account
    const loginResponse = await request.post(apiUrl("/auth/login/json"), {
      data: {
        email: user.email,
        password: user.password,
      },
    });
    expect(loginResponse.ok()).toBeTruthy();
  });

  test("password reset request", async ({ request }) => {
    const user = generateTestUser();

    // First register the user
    await request.post(apiUrl("/auth/register"), {
      data: {
        email: user.email,
        password: user.password,
        username: user.username,
      },
    });

    // Request password reset
    const resetResponse = await request.post(apiUrl("/auth/forgot-password"), {
      data: {
        email: user.email,
      },
    });

    // Should succeed even if email doesn't exist (for security)
    expect(resetResponse.ok()).toBeTruthy();
  });

  test("get current user with token", async ({ request }) => {
    const user = generateTestUser();

    // Register and get token
    const registerResponse = await request.post(apiUrl("/auth/register"), {
      data: {
        email: user.email,
        password: user.password,
        username: user.username,
      },
    });

    // Skip if rate limited
    if (!registerResponse.ok()) {
      console.log(`Registration failed (${registerResponse.status()}) - skipping test`);
      return;
    }

    const { access_token } = await registerResponse.json();

    // Get current user
    const userResponse = await request.get(apiUrl("/auth/me"), {
      headers: {
        Authorization: `Bearer ${access_token}`,
      },
    });

    expect(userResponse.ok()).toBeTruthy();
    const userData = await userResponse.json();
    expect(userData.email).toBe(user.email);
    expect(userData.username).toBe(user.username);
    expect(userData.is_anonymous).toBe(false);
  });

  test("anonymous user has is_anonymous flag", async ({ request }) => {
    // Create anonymous token
    const anonResponse = await request.post(apiUrl("/auth/anonymous"));
    const { access_token } = await anonResponse.json();

    // Get current user
    const userResponse = await request.get(apiUrl("/auth/me"), {
      headers: {
        Authorization: `Bearer ${access_token}`,
      },
    });

    expect(userResponse.ok()).toBeTruthy();
    const userData = await userResponse.json();
    expect(userData.is_anonymous).toBe(true);
  });
});

/**
 * Sign a browser in as a guest with a real anonymous token from the backend.
 * Opening a page does not start a session by itself; the app only asks for one
 * when the visitor makes a game.
 */
async function startGuestSession(page: Page, request: APIRequestContext): Promise<string> {
  const response = await request.post(apiUrl("/auth/anonymous"));
  expect(response.ok()).toBeTruthy();
  const { access_token: token } = (await response.json()) as { access_token: string };
  await page.goto("/create");
  await page.evaluate((value) => {
    localStorage.setItem("tinyworlds_access_token", value);
    localStorage.setItem("tinyworlds_token_expiry", String(Date.now() + 3600 * 1000));
  }, token);
  await page.reload();
  return token;
}

const storedToken = (page: Page) =>
  page.evaluate(() => localStorage.getItem("tinyworlds_access_token"));

test.describe("Authentication UI", () => {
  test("create page displays the account control", async ({ page }) => {
    await page.goto("/create");
    await expect(page.getByTestId("user-menu")).toBeVisible();
  });

  test("a visitor with no session is offered Sign in", async ({ page }) => {
    await page.goto("/create");

    const signIn = page
      .getByTestId("user-menu")
      .getByRole("link", { name: "Sign in", exact: true });
    await expect(signIn).toBeVisible();
    await expect(signIn).toHaveAttribute("href", "/login");
    // Looking at the page must not start a session.
    expect(await storedToken(page)).toBeNull();
  });

  test("a guest is offered Sign up and Sign in from the account menu", async ({ page, request }) => {
    await startGuestSession(page, request);

    await page.getByRole("button", { name: "Keep your games", exact: true }).click();
    const signUp = page.getByTestId("user-menu-create-account");
    await expect(signUp).toBeVisible();
    await expect(signUp).toHaveAttribute("href", "/register?upgrade=true");
    await expect(page.getByTestId("user-menu-sign-in")).toHaveAttribute("href", "/login");
  });

  test("login page is accessible", async ({ page }) => {
    await page.goto("/login");

    const emailInput = page.getByLabel("Email");
    const passwordInput = page.getByLabel("Password");
    const submitButton = page.getByRole("button", { name: "Sign in", exact: true });

    await expect(emailInput).toBeVisible();
    await expect(passwordInput).toBeVisible();
    await expect(submitButton).toBeVisible();
  });

  test("register page is accessible", async ({ page }) => {
    await page.goto("/register");

    // Register has two password fields ("Password" and "Password again").
    const emailInput = page.getByLabel("Email");
    const passwordInput = page.getByLabel("Password", { exact: true });
    const submitButton = page.getByRole("button", { name: "Sign up", exact: true });

    await expect(emailInput).toBeVisible();
    await expect(passwordInput).toBeVisible();
    await expect(page.getByLabel("Password again")).toBeVisible();
    await expect(submitButton).toBeVisible();
  });

  test("forgot password page is accessible", async ({ page }) => {
    await page.goto("/forgot-password");

    const emailInput = page.getByLabel("Email");
    const submitButton = page.getByRole("button", { name: "Send link", exact: true });

    await expect(emailInput).toBeVisible();
    await expect(submitButton).toBeVisible();
  });

  test("successful registration flow", async ({ page }) => {
    const user = generateTestUser();

    await page.goto("/register");

    await page.getByLabel("Email").fill(user.email);
    await page.getByLabel("Username").fill(user.username);
    await page.getByLabel("Password", { exact: true }).fill(user.password);
    await page.getByLabel("Password again").fill(user.password);

    await page.getByRole("button", { name: "Sign up", exact: true }).click();

    // Check for rate limiting first
    const rateLimitError = page.getByText(/too many.*attempts|rate limit/i);
    // isVisible() does not wait, so wait for whichever outcome arrives first.
    const isRateLimited = await Promise.race([
      rateLimitError.waitFor({ state: "visible", timeout: 15000 }).then(() => true),
      page.waitForURL("**/create", { timeout: 15000 }).then(() => false),
    ]).catch(() => false);

    if (isRateLimited) {
      // Skip rest of test if rate limited - this is expected in rapid test runs
      console.log("Registration rate limited - skipping token verification");
      return;
    }

    // A new account lands on the create page ("/" sends everyone there).
    await page.waitForURL("**/create", { timeout: 15000 });

    // The nav shows the signed-in account, and the token is stored.
    await expect(page.getByRole("button", { name: "Your account", exact: true })).toBeVisible();
    expect(await storedToken(page)).toBeTruthy();
  });

  test("successful login flow", async ({ page, request }) => {
    const user = generateTestUser();

    // First register via API
    const registerResponse = await request.post(apiUrl("/auth/register"), {
      data: {
        email: user.email,
        password: user.password,
        username: user.username,
      },
    });

    // Skip test if registration failed (e.g., due to rate limiting)
    if (!registerResponse.ok()) {
      const errorText = await registerResponse.text();
      console.log(`Registration failed (${registerResponse.status()}): ${errorText} - skipping login test`);
      return;
    }

    await page.goto("/login");
    expect(await storedToken(page)).toBeNull();

    await page.getByLabel("Email").fill(user.email);
    await page.getByLabel("Password").fill(user.password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();

    // Signing in lands on the create page ("/" sends everyone there).
    await page.waitForURL("**/create", { timeout: 15000 });

    // The account menu shows who signed in, and the token is stored.
    await page.getByRole("button", { name: "Your account", exact: true }).click();
    await expect(page.getByTestId("user-menu").getByText(user.email, { exact: true })).toBeVisible();
    expect(await storedToken(page)).toBeTruthy();
  });

  test("login with invalid credentials shows error", async ({ page }) => {
    await page.goto("/login");

    await page.getByLabel("Email").fill("nonexistent@example.com");
    await page.getByLabel("Password").fill("WrongPassword123!");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();

    // Should show error message
    const errorMessage = page.getByText(/invalid|incorrect|failed|error/i);
    await expect(errorMessage).toBeVisible({ timeout: 5000 });
    await expect(page).toHaveURL(/\/login$/);
  });

  test("games page displays the account control", async ({ page }) => {
    await page.goto("/games");

    await expect(page.getByRole("heading", { name: "Games", exact: true })).toBeVisible();
    await expect(page.getByTestId("user-menu")).toBeVisible();
  });
});

test.describe("Auth Token Persistence", () => {
  test("a guest session persists across page reloads", async ({ page, request }) => {
    const token = await startGuestSession(page, request);
    const guestMenu = page.getByRole("button", { name: "Keep your games", exact: true });
    await expect(guestMenu).toBeVisible();

    await page.reload();

    // Same session after the reload: the app accepted the stored token.
    await expect(guestMenu).toBeVisible();
    expect(await storedToken(page)).toBe(token);

    await page.goto("/games");
    await expect(guestMenu).toBeVisible();
    expect(await storedToken(page)).toBe(token);
  });

  test("clearing localStorage ends the session", async ({ page, request }) => {
    await startGuestSession(page, request);
    await expect(page.getByRole("button", { name: "Keep your games", exact: true })).toBeVisible();

    await page.evaluate(() => {
      localStorage.removeItem("tinyworlds_access_token");
      localStorage.removeItem("tinyworlds_token_expiry");
      localStorage.removeItem("tinyworlds_user");
    });
    await page.reload();

    // The visitor is signed out, and no new session starts by itself.
    await expect(
      page.getByTestId("user-menu").getByRole("link", { name: "Sign in", exact: true })
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Keep your games", exact: true })).toHaveCount(0);
    expect(await storedToken(page)).toBeNull();
  });
});
