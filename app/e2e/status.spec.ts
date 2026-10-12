import { expect, test } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// The header says whether the display and the layers came up (GET /api/status): the test servers run the mock display.
test.beforeEach(async ({ page }) => stubMapTiles(page))

test("the header shows the device is running, and what each part reports", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	const status = page.getByTestId("status")
	await expect(status).toHaveAttribute("data-state", "ok", { timeout: 20000 })
	await status.click()
	await expect(page.getByText("Display: Running.")).toBeVisible()
	await expect(page.getByText("Timer tasks: Running.")).toBeVisible()
	watch.expectNone()
})
