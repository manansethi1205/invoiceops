import { expect, test } from "@playwright/test";

test("protected pages redirect to sign-in and local logout clears the session", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByRole("heading", { name: "Sign in to InvoiceOps" })).toBeVisible();
  await page.getByLabel("Synthetic local identity").selectOption("reviewer");
  await page.getByRole("button", { name: "Sign in locally" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);
  await page.goto("/reviews");
  await expect(page).toHaveURL(/\/login/);
});

test("auditor is redirected away from operator-only intake", async ({ page }) => {
  const response = await page.request.post("/api/auth/dev-login", { form: { role: "auditor" }, maxRedirects: 0 });
  expect(response.status()).toBe(303);
  await page.goto("/intake");
  await expect(page).toHaveURL(/\/forbidden/);
  await expect(page.getByRole("heading", { name: "Access denied" })).toBeVisible();
});
