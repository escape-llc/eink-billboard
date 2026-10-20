import { expect, test } from "@playwright/test"
import { PROTECTED, TOKEN } from "./servers"
import { stubMapTiles, watchProblems, signInWith } from "./support"

// The System page's activity follows the device through the telemetry link (a WebSocket) on the real servers: the mock display draws the
// playlist's pages, and a change of settings is reported.
test.beforeEach(async ({ page }) => stubMapTiles(page))

test("the activity goes live, shows what the panel shows, and reports a change of settings", async ({ page, request }) => {
	const watch = watchProblems(page)
	await page.goto("/#/system")
	const gutter = page.getByRole("region", { name: "Device activity" })
	await expect(gutter.getByTestId("link-status")).toHaveText("Live")
	// the mock display drew the playlist's page when the server started: its thumbnail loads
	const now = gutter.getByRole("region", { name: "Now showing" }).getByRole("button", { name: /full size/ }).getByRole("img")
	await expect(now).toBeVisible({ timeout: 20000 })
	await expect.poll(() => now.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0)

	// and who made it, on a line with its layer's glyph: the playlist, the track and the plugin; or, in the minute after a quarter hour,
	// the fixture's Quarter-hour clock task on the priority layer (it covers the playlist then: the test cannot choose the time it runs)
	const layers = gutter.getByTestId("layers")
	await expect(layers).toContainText(/(.+ › .+ \(.+\))|(Quarter-hour clock \(.+\))/)
	await expect(layers.locator("i.mi").first()).toBeVisible()
	await expect(layers.getByRole("img", { name: /Background|Foreground|Priority/ }).first()).toBeVisible()
	// the layer is said once, by its glyph: no chip repeats it
	await expect(gutter.getByRole("region", { name: "Now showing" }).getByText(/^(override|background)$/)).toHaveCount(0)

	// somebody saves the system settings: the change reaches the activity by area, not by path
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
	await page.goto(`${PROTECTED.url}/#/system`)
	await signInWith(page, "API token", TOKEN)
	await expect(page.getByTestId("link-status")).toHaveText("Live", { timeout: 15000 })
	watch.expectNone()
})

test("in a short window the System page scrolls inside its area and the events inside theirs, so the last ones can be reached", async ({ page }) => {
	const watch = watchProblems(page)
	await page.setViewportSize({ width: 1200, height: 450 })
	await page.goto("/#/system")
	const activity = page.getByRole("region", { name: "Device activity" })
	await expect(activity.getByTestId("link-status")).toHaveText("Live")
	const events = activity.getByRole("region", { name: "Events" })
	await expect(events.getByRole("listitem").first()).toBeVisible({ timeout: 20000 })

	// nothing is taller than the window: the page scrolls inside its area, to its end (backup and restore is the last part) ...
	const router = page.locator(".router-view")
	expect(await page.evaluate(() => document.querySelector(".router-view")!.getBoundingClientRect().bottom)).toBeLessThanOrEqual(450)
	expect(await router.evaluate(e => e.scrollHeight - e.clientHeight)).toBeGreaterThan(0)
	await router.evaluate(e => { e.scrollTop = e.scrollHeight })
	await expect(page.getByRole("region", { name: "Backup and restore" })).toBeInViewport()
	// ... and the events list scrolls inside its own box: its last event can be reached
	const list = events.getByRole("list")
	await list.evaluate(e => { e.scrollTop = e.scrollHeight })
	const last = events.getByRole("listitem").last()
	await last.evaluate(e => { e.scrollIntoView({ block: "end" }) })
	await expect(last).toBeInViewport()
	watch.expectNone()
})

test("the System page's parts have their own surface, which follows the theme", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/system")
	const gutter = page.getByRole("region", { name: "Device activity" })
	await expect(gutter.getByTestId("link-status")).toHaveText("Live")
	const background = () => gutter.evaluate(el => getComputedStyle(el).backgroundColor)
	const light = (rgb: string) => { const [r, g, b] = (rgb.match(/\d+/g) ?? []).map(Number); return ((r ?? 0) + (g ?? 0) + (b ?? 0)) / 765 }
	await page.evaluate(() => document.documentElement.classList.remove("app-dark-mode"))
	// painted, not the page showing through
	expect(await background()).not.toBe("rgba(0, 0, 0, 0)")
	expect(light(await background())).toBeGreaterThan(0.6)
	await page.evaluate(() => document.documentElement.classList.add("app-dark-mode"))
	expect(light(await background())).toBeLessThan(0.25)
	watch.expectNone()
})

test("the activity is the larger part of the System page, and its player and events are side by side", async ({ page }) => {
	const watch = watchProblems(page)
	await page.setViewportSize({ width: 1500, height: 900 })
	await page.goto("/#/system")
	const activity = page.getByRole("region", { name: "Device activity" })
	await expect(activity.getByTestId("link-status")).toHaveText("Live")
	const events = activity.getByRole("region", { name: "Events" })
	await expect(events.getByRole("listitem").first()).toBeVisible({ timeout: 20000 })
	const now = activity.getByRole("group", { name: "Playback" })
	const [a, e, p, machine] = await Promise.all([activity.boundingBox(), events.boundingBox(), now.boundingBox(), page.getByRole("region", { name: "Machine" }).boundingBox()])
	// the activity takes more than the facts beside it
	expect(a!.width).toBeGreaterThan(machine!.width)
	// the player's column is beside the events, not above them
	expect(e!.x).toBeGreaterThan(p!.x + p!.width - 2)
	expect(Math.abs(e!.y - p!.y)).toBeLessThan(60)
	// a narrow window stacks them again
	await page.setViewportSize({ width: 1000, height: 900 })
	const [stackedPlayer, stackedEvents] = await Promise.all([now.boundingBox(), events.boundingBox()])
	expect(stackedEvents!.y).toBeGreaterThan(stackedPlayer!.y)
	watch.expectNone()
})
