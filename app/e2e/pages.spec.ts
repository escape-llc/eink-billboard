import { expect, test } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// The app uses hash routes: /#/settings
test.describe("every page renders from the seeded storage, without errors", () => {
	test.beforeEach(async ({ page }) => stubMapTiles(page))

	test("welcome", async ({ page }) => {
		const watch = watchProblems(page)
		await page.goto("/")
		await expect(page.getByText("Welcome to eInk Billboard!")).toBeVisible()
		await expect(page).toHaveTitle("eInk Billboard")
		// the favicon comes from the bundle's public folder
		expect((await page.request.get("/logo.svg")).status()).toBe(200)
		watch.expectNone()
	})

	test("settings shows the system settings form", async ({ page }) => {
		const watch = watchProblems(page)
		await page.goto("/#/settings")
		for (const tab of ["System", "Display", "Theme", "Plugins", "Data Sources"]) {
			await expect(page.getByRole("tab", { name: tab })).toBeVisible()
		}
		for (const label of ["Timezone", "Locale", "Time Format", "Location"]) {
			await expect(page.locator("label", { hasText: label })).toBeVisible()
		}
		watch.expectNone()
	})

	test("schedule shows the timer tasks of the week", async ({ page }) => {
		const watch = watchProblems(page)
		await page.goto("/#/schedule")
		// the enabled task fires every quarter hour; the paused one is not rendered (the timer layer would not run it either)
		await expect(page.getByText(/Quarter-hour clock/).first()).toBeVisible()
		for (const day of ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]) {
			await expect(page.getByText(day, { exact: false }).first()).toBeVisible()
		}
		watch.expectNone()
	})

	test("playlist shows the tracks", async ({ page }) => {
		const watch = watchProblems(page)
		await page.goto("/#/playlist")
		await expect(page.getByText("E2E Playlist").first()).toBeVisible()
		await expect(page.getByText("Morning slides")).toBeVisible()
		await expect(page.getByText("Evening slides")).toBeVisible()
		watch.expectNone()
	})

	test("the browser stores nothing but the theme", async ({ page }) => {
		const watch = watchProblems(page)
		await page.goto("/#/settings")
		await expect(page.getByRole("tab", { name: "System" })).toBeVisible()
		await page.getByRole("button", { name: "Theme Control" }).click()
		await page.locator(".primary-button").nth(3).click()
		const stored = await page.evaluate(() => ({ local: Object.keys(localStorage), session: Object.keys(sessionStorage) }))
		expect(stored.local.length, "the theme is saved").toBeGreaterThan(0)
		expect(stored.local.filter(k => !k.startsWith("theme-")), "localStorage keys besides the theme").toEqual([])
		expect(stored.session, "sessionStorage keys").toEqual([])
		watch.expectNone()
	})

	test("the theme selector applies a colour", async ({ page }) => {
		const watch = watchProblems(page)
		await page.goto("/")
		await page.getByRole("button", { name: "Theme Control" }).click()
		const swatches = page.locator(".primary-button")
		// 16 primary colours and 8 surfaces
		await expect(swatches).toHaveCount(24)
		await swatches.nth(3).click()
		await expect(swatches.nth(3)).toHaveClass(/active-color/)
		watch.expectNone()
	})
})

test("the plugin and datasource selectors show names, not [object Object]", async ({ page }) => {
	await stubMapTiles(page)
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Data Sources" }).click()
	const select = page.getByRole("tabpanel").locator(".p-select").first()
	await select.click()
	// options are identified by their name, not by the string form of the object
	await page.getByRole("option", { name: /openai-image/ }).click()
	await expect(select).toContainText("openai-image")
	await expect(select).not.toContainText("[object Object]")
	await expect(select.getByRole("combobox")).toHaveAttribute("aria-label", "openai-image")
	watch.expectNone()
})
