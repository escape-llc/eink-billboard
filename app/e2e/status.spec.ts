import { expect, test } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// The System page says whether the display and the layers came up (GET /api/status): the test servers run the mock display.
test.beforeEach(async ({ page }) => stubMapTiles(page))

test("the System page shows the device is running, and what each part reports", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/system")
	await expect(page.getByTestId("device-status")).toHaveAttribute("data-state", "ok", { timeout: 20000 })
	// a pill per part, its glyph named for a screen reader, and what it said in the title
	const parts = page.getByTestId("parts")
	await expect(parts.getByRole("listitem", { name: "Display running" })).toHaveAttribute("title", "Display: Running.")
	await expect(parts.getByRole("listitem", { name: "Timer tasks running" })).toBeVisible()
	watch.expectNone()
})

test("the System page reports the machine and the storage by data source, with no host name or path", async ({ page, request }) => {
	const watch = watchProblems(page)
	await page.goto("/#/system")
	// the device is one card: the application's parts, the machine, and the Pi when it is one
	const machine = page.getByRole("region", { name: "Device" })
	await expect(machine.getByRole("list", { name: "Machine" })).toBeVisible({ timeout: 20000 })
	await expect(machine.getByRole("list", { name: "Application" })).toBeVisible()
	// the header says which build the page is from, and the Machine card compares it with the server's (the test servers are not in a container: the server does not know its commit)
	await expect(page.getByTestId("app-version")).toHaveText(/^v\S+ \(\S+\)$/)
	await expect(machine.getByTestId("builds")).toHaveAttribute("title", /web app dev$/)
	await expect(machine.getByText("Different builds")).toHaveCount(0)
	// the machine and the app each say how long they have been up (the app started a moment ago)
	await expect(machine.getByRole("listitem", { name: /^up \d/ })).toBeVisible()
	await expect(machine.getByTestId("app-uptime")).toHaveText(/^\d+ (s|min)|^\d+ h/)
	await expect(machine.getByTestId("memory")).toHaveAttribute("title", /^Memory: .* in use \(\d+%\)$/)
	// the storage starts closed, with its totals as pills; open, a pill per area, data source and plugin, and the total in words
	const storage = page.getByRole("region", { name: "Storage" })
	await expect(storage.getByTestId("storage-pills").getByRole("listitem").first()).toHaveAccessibleName(/^size \d+(\.\d)? (bytes|KB|MB|GB)$/)
	await expect(storage.getByRole("list", { name: "Data sources" })).toHaveCount(0)
	await storage.getByRole("button", { name: "Storage" }).click()
	await expect(storage.getByRole("button", { name: "Storage" })).toHaveAttribute("aria-expanded", "true")
	await expect(storage.getByRole("list", { name: "Data sources" })).toBeVisible()
	await expect(storage.getByRole("list", { name: "Areas" }).getByRole("listitem").filter({ hasText: "settings" })).toHaveAttribute("title", /^settings: .* in \d+ files?$/)
	// the Pi's own row appears only on a Pi: the test machine is not one
	await expect(page.getByTestId("pi")).toHaveCount(0)
	await expect(page.getByText("Raspberry Pi", { exact: true })).toHaveCount(0)
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
		body.usage = [{ id: "openweathermap-api", name: "OpenWeatherMap", today: period(4, 0), week: period(20, 1), month: period(70, 2), lastLimited: "2026-10-21T12:17:09.5+02:00",
			quota: { limit: 100, resetDay: 1, used: 25, percent: 25, since: "2026-10-01", resets: "2026-11-01" } }]
		await route.fulfill({ response: real, json: body })
	})
	await page.goto("/#/system")
	const usage = page.getByRole("region", { name: "API usage" })
	// closed, a line per source as pills (a glyph or label on its tone, the value beside it); open, a line of pills per period
	const summary = usage.getByTestId("usage-summary")
	await expect(summary).toContainText("OpenWeatherMap", { timeout: 20000 })
	const month = summary.getByRole("list", { name: "OpenWeatherMap, this month" }).getByRole("listitem")
	await expect(month).toHaveText(["70", "2", "75%", "quota25%"])
	await expect(month.nth(0)).toHaveAccessibleName("calls 70")
	await expect(month.nth(1)).toHaveAccessibleName("failed 2")
	await usage.getByRole("button", { name: "API usage" }).click()
	await expect(usage.getByRole("list", { name: "OpenWeatherMap, Month" }).getByRole("listitem")).toHaveText(["70", "2", "8.2 KB", "140 KB", "75%"])
	await expect(usage.getByRole("list", { name: "OpenWeatherMap, Today" }).getByRole("listitem", { name: /^failed/ })).toHaveCount(0)
	// what the service answered, a pill each, and the plan's share
	await expect(usage.getByTestId("answers").getByRole("listitem")).toHaveCount(2)
	await expect(usage.getByTitle("200 OK: 68 calls")).toBeVisible()
	await expect(usage.getByTitle("429 Too Many Requests: 2 calls")).toBeVisible()
	await expect(usage.getByText("25 of 100 calls since Oct 1 (25%), resets Nov 1")).toBeVisible()
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
	await expect(page.getByTestId("device-status")).toHaveAttribute("data-state", "ok")
	watch.expectNone()
})

test("a card of the System page opens and closes from its title", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/system")
	const machine = page.getByRole("region", { name: "Device" })
	await expect(machine.getByTestId("machine")).toBeVisible({ timeout: 20000 })
	await machine.getByRole("button", { name: "Device" }).click()
	await expect(machine.getByRole("button", { name: "Device" })).toHaveAttribute("aria-expanded", "false")
	await expect(machine.getByTestId("machine")).toHaveCount(0)
	await machine.getByRole("button", { name: "Device" }).click()
	await expect(machine.getByTestId("machine")).toBeVisible()
	watch.expectNone()
})
