import { test as base, expect } from "@playwright/test";

export const test = base.extend<{ signedIn: void }>({
  signedIn: [async ({ page }, use) => {
    const response = await page.request.post("/api/auth/dev-login", { form: { role: "reviewer" }, maxRedirects: 0 });
    expect(response.status()).toBe(303);
    await use();
  }, { auto: true }],
});

export { expect };
