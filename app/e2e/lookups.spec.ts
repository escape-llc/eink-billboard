import { expect, test } from "@playwright/test"
import { OPEN } from "./servers"
import { stubMapTiles, watchProblems } from "./support"

// Regression for #43: lookups were requested from http://api/... and the dropdowns stayed empty.
test("the Timezone and Locale lists are loaded from this server", async ({ page }) => {
	await stubMapTiles(page)
	const watch = watchProblems(page)
	const lookups: string[] = []
	page.on("request", r => { if (r.url().includes("/lookups/")) lookups.push(r.url()) })
	await page.goto("/#/settings")

	await page.locator(".p-select").filter({ hasText: "New York" }).first().click()
	// every region/city zone, well over a hundred
	expect(await page.getByRole("option").count()).toBeGreaterThan(100)
	await page.keyboard.press("Escape")

	await page.locator(".p-select").filter({ hasText: "English" }).first().click()
	await expect(page.getByRole("option")).toHaveCount(4)
	await expect(page.getByRole("option").filter({ hasText: "Français" })).toBeVisible()

	expect(lookups.length).toBeGreaterThan(0)
	for (const url of lookups) expect(url.startsWith(`${OPEN.url}/api/lookups/`), url).toBe(true)
	watch.expectNone()
})
