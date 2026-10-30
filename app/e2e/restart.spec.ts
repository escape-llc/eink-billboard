import { expect, test } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// The restart is stubbed (nothing here may stop the test servers): what the server says is waiting, the call that asks, and the page that waits.
async function stubRestart(page: import("@playwright/test").Page, state: { available: boolean, waiting: string[] }) {
	const asked: string[] = []
	await page.route("**/api/system/restart", route => {
		if (route.request().method() === "POST") {
			asked.push("restart")
			return route.fulfill({ status: 202, json: { success: true } })
		}
		return route.fulfill({ json: state })
	})
	return asked
}

test.beforeEach(async ({ page }) => { await stubMapTiles(page) })

test("a display change waiting for a restart is said on every page, and the banner restarts after a confirmation", async ({ page }) => {
	const watch = watchProblems(page)
	const asked = await stubRestart(page, { available: true, waiting: ["The display type was changed: the display reads it when the app starts."] })
	await page.goto("/#/settings")
	const banner = page.getByTestId("restart-banner")
	await expect(banner).toContainText("The display type was changed")
	await page.getByTestId("restart-banner-button").click()
	await page.getByRole("button", { name: "Cancel" }).click()
	expect(asked).toEqual([])
	await page.getByTestId("restart-banner-button").click()
	await page.getByRole("button", { name: "Restart", exact: true }).last().click()
	await expect(page.getByTestId("restart-overlay")).toBeVisible()
	expect(asked).toEqual(["restart"])
	watch.expectNone()
})

test("with nothing waiting there is no banner, and the System page's red button asks first", async ({ page }) => {
	const watch = watchProblems(page)
	const asked = await stubRestart(page, { available: true, waiting: [] })
	await page.goto("/#/system")
	await expect(page.getByTestId("restart-banner")).toHaveCount(0)
	await page.getByTestId("restart-app").click()
	await expect(page.getByText("The app stops and starts again")).toBeVisible()
	expect(asked).toEqual([])
	await page.getByRole("button", { name: "Restart", exact: true }).last().click()
	await expect(page.getByTestId("restart-overlay")).toBeVisible()
	expect(asked).toEqual(["restart"])
	watch.expectNone()
})

test("where nothing starts the app again the banner says so and the button is off", async ({ page }) => {
	const watch = watchProblems(page)
	await stubRestart(page, { available: false, waiting: ["The display type was changed: the display reads it when the app starts."] })
	await page.goto("/#/system")
	await expect(page.getByTestId("restart-banner")).toContainText("Restart the app where it runs")
	await expect(page.getByTestId("restart-banner-button")).toHaveCount(0)
	await expect(page.getByTestId("restart-app")).toBeDisabled()
	watch.expectNone()
})
