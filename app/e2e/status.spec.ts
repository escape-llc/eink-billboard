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
	const storage = page.getByRole("region", { name: "Storage" })
	await expect(storage.getByRole("table", { name: "Data sources" })).toBeVisible()
	await expect(storage.getByRole("rowheader", { name: "settings" })).toBeVisible()
	// the Pi's own card appears only on a Pi: the test machine is not one
	await expect(page.getByRole("region", { name: "Raspberry Pi" })).toHaveCount(0)
	// the left menu has the page, and the toolbar has neither the status button nor the activity button
	await expect(page.getByRole("button", { name: "Activity" })).toHaveCount(0)
	await page.locator("button[aria-controls=overlay_tmenu]").first().click()
	await expect(page.getByRole("link", { name: "System" })).toBeVisible()
	const body = await (await request.get("/api/system")).text()
	expect(body).not.toMatch(/\.storage|[A-Za-z]:\\/)
	watch.expectNone()
})
