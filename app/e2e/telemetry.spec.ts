import { expect, test } from "@playwright/test"
import { PROTECTED, TOKEN } from "./servers"
import { stubMapTiles, watchProblems, signInWith } from "./support"

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

	// and which track made it: the playlist, the track and the plugin
	await expect(gutter.getByTestId("origins")).toContainText(/.+ › .+ \(.+\)/)
	await expect(gutter.getByTestId("origins").locator("i.mi").first()).toBeVisible()

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
	await page.goto(`${PROTECTED.url}/#/settings`)
	await signInWith(page, "API token", TOKEN)
	await page.getByRole("button", { name: "Activity" }).click()
	await expect(page.getByTestId("link-status")).toHaveText("Live", { timeout: 15000 })
	watch.expectNone()
})

test("in a short window the page and the gutter stay inside it and scroll, so the last events can be reached", async ({ page }) => {
	const watch = watchProblems(page)
	await page.setViewportSize({ width: 1200, height: 450 })
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Data Sources" }).click()
	await page.getByRole("tabpanel").locator(".p-select").first().click()
	await page.getByRole("option", { name: /^calendar/ }).click()
	await page.getByRole("button", { name: "Activity" }).click()
	const gutter = page.getByRole("complementary", { name: "Device activity" })
	await expect(gutter.getByTestId("link-status")).toHaveText("Live")
	await expect(gutter.getByRole("region", { name: "Events" }).getByRole("listitem").first()).toBeVisible({ timeout: 20000 })

	// nothing is taller than the window ...
	const heights = await page.evaluate(() => ({
		window: innerHeight,
		gutter: document.querySelector(".gutter")!.getBoundingClientRect().bottom,
		router: document.querySelector(".router-view")!.getBoundingClientRect().bottom,
	}))
	expect(heights.gutter).toBeLessThanOrEqual(heights.window)
	expect(heights.router).toBeLessThanOrEqual(heights.window)
	// ... the long settings page scrolls inside its area, to its end ...
	const router = page.locator(".router-view")
	expect(await router.evaluate(e => e.scrollHeight - e.clientHeight)).toBeGreaterThan(0)
	await router.evaluate(e => { e.scrollTop = e.scrollHeight })
	await expect(page.getByRole("button", { name: "Add to Holidays" })).toBeInViewport()
	// ... and so does the gutter: its last event can be scrolled to
	await gutter.evaluate(e => { e.scrollTop = e.scrollHeight })
	const last = gutter.getByRole("region", { name: "Events" }).getByRole("listitem").last()
	await last.evaluate(e => { e.scrollIntoView({ block: "end" }) })
	await expect(last).toBeInViewport()
	watch.expectNone()
})
