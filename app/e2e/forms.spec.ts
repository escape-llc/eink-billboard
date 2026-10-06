import { expect, test } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

test.beforeEach(async ({ page }) => stubMapTiles(page))

// the row a form field renders into: its label plus the control(s)
const row = (page: import("@playwright/test").Page, label: string) =>
	page.locator(".p-inputgroup").filter({ has: page.locator("label", { hasText: label }) })

test("a boolean field is one toggle, not a toggle followed by a text box", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Display" }).click()
	const rotate = row(page, "Rotate 180")
	await expect(rotate).toHaveCount(1)
	await expect(rotate.locator(".p-toggleswitch")).toHaveCount(1)
	await expect(rotate.locator("input[type=text]")).toHaveCount(0)
	watch.expectNone()
})
