import { test, expect } from '@playwright/test';

// Check the document title instead of visible DOM text (app is JS-rendered)
test('homepage loads and has correct title', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveTitle(/Swarm Factory/);
});
