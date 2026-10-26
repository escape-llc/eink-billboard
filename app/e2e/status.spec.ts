import { expect, test } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// The System page says whether the display and the layers came up (GET /api/status): the test servers run the mock display.
test.beforeEach(async ({ page }) => stubMapTiles(page))

test("the System page shows the device is running, and what each part reports", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/system")
	await expect(page.getByTestId("status")).toHaveAttribute("data-state", "ok", { timeout: 20000 })
	await expect(page.getByText("Display: Running.")).toBeVisible()
	await expect(page.getByText("Timer tasks: Running.")).toBeVisible()
	watch.expectNone()
})

test("the System page reports the machine and the storage by data source, with no host name or path", async ({ page, request }) => {
	const watch = watchProblems(page)
	await page.goto("/#/system")
	const machine = page.getByRole("region", { name: "Machine" })
	await expect(machine.getByText("Python")).toBeVisible({ timeout: 20000 })
	// the header says which build the page is from, and the Machine card compares it with the server's (the test servers are not in a container: the server does not know its commit)
	await expect(page.getByTestId("app-version")).toHaveText(/^v\S+ \(\S+\)$/)
	await expect(machine.getByTestId("builds")).toContainText("web app dev")
	await expect(machine.getByText("Different builds")).toHaveCount(0)
	// the machine and the app each say how long they have been up (the app started a moment ago)
	await expect(machine.getByText("Machine up for")).toBeVisible()
	await expect(machine.getByTestId("app-uptime")).toHaveText(/^\d+ (s|min)|^\d+ h/)
	await expect(machine.getByRole("meter", { name: "Memory in use" })).toBeVisible()
	// the storage starts closed, with its total; open, it has the tables (and the total again)
	const storage = page.getByRole("region", { name: "Storage" })
	await expect(storage.getByTestId("storage-total")).toHaveText(/^\d+(\.\d)? (bytes|KB|MB|GB) in \d+ files?(, .*% of the disk)?$/)
	await expect(storage.getByRole("table")).toHaveCount(0)
	await storage.getByRole("button", { name: "Storage" }).click()
	await expect(storage.getByRole("button", { name: "Storage" })).toHaveAttribute("aria-expanded", "true")
	await expect(storage.getByRole("table", { name: "Data sources" })).toBeVisible()
	await expect(storage.getByRole("rowheader", { name: "settings" })).toBeVisible()
	// the Pi's own card appears only on a Pi: the test machine is not one
	await expect(page.getByRole("region", { name: "Raspberry Pi" })).toHaveCount(0)
	// the left menu has the page, and the app's toolbar has no activity button (the one "Activity" button is the card's title, which opens and closes it)
	await expect(page.getByRole("button", { name: "Activity" })).toHaveCount(1)
	await expect(page.getByRole("region", { name: "Activity" }).getByRole("button", { name: "Activity" })).toHaveCount(1)
	await page.locator("button[aria-controls=overlay_tmenu]").first().click()
	await expect(page.getByRole("link", { name: "System" })).toBeVisible()
	const body = await (await request.get("/api/system")).text()
	expect(body).not.toMatch(/\.storage|[A-Za-z]:\\/)
	watch.expectNone()
})

test("the System page says what each API data source has asked of its service", async ({ page }) => {
	const watch = watchProblems(page)
	const period = (calls: number, failed: number) => ({ calls, status: failed ? { "200": calls - failed, "429": failed } : { "200": calls }, sent: 120 * calls, received: 2048 * calls, cache: { hit: 6, miss: 2 }, cacheBytes: { hit: 6000, miss: 2000 }, hitRate: 0.75, bytesSaved: 6000 })
	// no API data source runs against a real service in these servers: the page is given what the server would count (the counting itself is in test_api_metering)
	await page.route("**/api/system", async route => {
		const real = await route.fetch()
		const body = await real.json()
		body.usage = [{ id: "openweathermap-api", name: "OpenWeatherMap", today: period(4, 0), week: period(20, 1), month: period(70, 2), lastLimited: "2026-10-21T12:17:09.5+02:00" }]
		await route.fulfill({ response: real, json: body })
	})
	await page.goto("/#/system")
	const usage = page.getByRole("region", { name: "API usage" })
	// closed, a line per source; open, its table
	await expect(usage.getByTestId("usage-summary")).toHaveText("OpenWeatherMap: 70 calls this month, 2 failed, 75% from cache", { timeout: 20000 })
	await usage.getByRole("button", { name: "API usage" }).click()
	const table = usage.getByRole("table", { name: "OpenWeatherMap" })
	await expect(table).toBeVisible()
	const month = table.getByRole("row", { name: /^Month/ })
	await expect(month.getByRole("cell").nth(0)).toHaveText("70")
	await expect(month.getByRole("cell").nth(1)).toHaveText("2")
	await expect(month.getByRole("cell").nth(4)).toHaveText("75%")
	await expect(usage.getByText("200 × 68, 429 × 2")).toBeVisible()
	// the moment is the device's wall clock as the server wrote it, not converted to the browser's zone
	await expect(usage.getByText("2026-10-21 12:17")).toBeVisible()
	watch.expectNone()
})

test("with nothing counted yet the API usage card says so", async ({ page }) => {
	const watch = watchProblems(page)
	await page.route("**/api/system", async route => {
		const real = await route.fetch()
		const body = await real.json()
		body.usage = []
		await route.fulfill({ response: real, json: body })
	})
	await page.goto("/#/system")
	await expect(page.getByRole("region", { name: "API usage" }).getByText("No API data source has made a call yet.")).toBeVisible({ timeout: 20000 })
	watch.expectNone()
})

test("every page's header says how the device is, and opens the System page", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	const indicator = page.getByTestId("device-status")
	// the test servers' parts all start: once the link is live and the start has said so, it is running
	await expect(indicator).toHaveAttribute("data-state", "ok", { timeout: 20000 })
	await expect(indicator).toHaveText("Running")
	await indicator.click()
	await expect(page).toHaveURL(/#\/system/)
	await expect(page.getByTestId("status")).toHaveAttribute("data-state", "ok")
	watch.expectNone()
})

test("a card of the System page opens and closes from its title", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/system")
	const machine = page.getByRole("region", { name: "Machine" })
	await expect(machine.getByText("Python")).toBeVisible({ timeout: 20000 })
	await machine.getByRole("button", { name: "Machine" }).click()
	await expect(machine.getByRole("button", { name: "Machine" })).toHaveAttribute("aria-expanded", "false")
	await expect(machine.getByText("Python")).toHaveCount(0)
	await machine.getByRole("button", { name: "Machine" }).click()
	await expect(machine.getByText("Python")).toBeVisible()
	watch.expectNone()
})
