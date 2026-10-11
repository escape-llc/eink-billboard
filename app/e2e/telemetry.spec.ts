import { expect, test } from "@playwright/test"
import { PROTECTED, TOKEN } from "./servers"
import { stubMapTiles, watchProblems } from "./support"

// The activity gutter follows the device through the telemetry link (a WebSocket) on the real servers: the mock display draws the
// playlist's pages, and a change of settings is reported.
test.beforeEach(async ({ page }) => stubMapTiles(page))

test("the gutter goes live, shows what the panel shows, and reports a change of settings", async ({ page, request }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("button", { name: "Activity" }).click()
	const gutter = page.getByRole("complementary", { name: "Device activity" })
	await expect(gutter.getByTestId("link-status")).toHaveText("Live")
	// the mock display drew the playlist's page when the server started: its thumbnail loads
	const now = gutter.getByRole("region", { name: "Now showing" }).getByRole("img")
	await expect(now).toBeVisible({ timeout: 20000 })
	await expect.poll(() => now.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0)

	// somebody saves the system settings: the change reaches the gutter by area, not by path
	const current = await (await request.get("/api/settings/system")).json()
	expect((await request.put("/api/settings/system", { data: current })).ok()).toBeTruthy()
	await expect(gutter.getByText("The settings changed.").first()).toBeVisible({ timeout: 15000 })
	await expect(gutter.getByText(/storage|\.json/)).toHaveCount(0)

	// the full image opens in a dialog
	await now.click()
	await expect(page.getByRole("dialog").getByRole("img")).toBeVisible()
	watch.expectNone()
})

test("on the server with a token, the link connects once the page has signed in", async ({ page }) => {
	const watch = watchProblems(page, [401])
	page.on("dialog", d => d.accept(TOKEN))
	await page.goto(`${PROTECTED.url}/#/settings`)
	await page.getByRole("button", { name: "Activity" }).click()
	await expect(page.getByTestId("link-status")).toHaveText("Live", { timeout: 15000 })
	watch.expectNone()
})
