import { expect, test, type APIRequestContext } from "@playwright/test"
import { choose, saveButton, stubMapTiles, watchProblems } from "./support"

// These tests change the settings of the shared server, one after the other.
test.describe.configure({ mode: "serial" })
test.beforeEach(async ({ page }) => stubMapTiles(page))

const system = async (request: APIRequestContext) => (await request.get("/api/settings/system")).json()
const showing = (page: import("@playwright/test").Page, text: string) => page.locator(".p-select").filter({ hasText: text }).first()

test("saving a changed setting stores it", async ({ page, request }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await expect(showing(page, "English")).toBeVisible()
	await choose(page, "English", "Français")
	await expect(saveButton(page)).toBeEnabled()
	await saveButton(page).click()
	await expect(page.getByText("Settings saved successfully")).toBeVisible()
	expect((await system(request)).locale).toBe("fr-FR")
	watch.expectNone()
})

test("a stale save is refused with the server's message, and overwrites nothing", async ({ page, request }) => {
	const watch = watchProblems(page, [409], [/Revision mismatch/])
	await page.goto("/#/settings")
	await expect(showing(page, "Français")).toBeVisible()
	// somebody else changes the settings after this page loaded them
	const doc = await system(request)
	const put = await request.put("/api/settings/system", { data: { ...doc, timeFormat: "12h" } })
	expect(put.ok()).toBe(true)

	await choose(page, "Français", "Deutsch")
	await saveButton(page).click()
	await expect(page.getByText(/Revision mismatch/)).toBeVisible()
	const after = await system(request)
	expect(after.locale).toBe("fr-FR")
	expect(after.timeFormat).toBe("12h")
	watch.expectNone()
})

test("reloading shows the stored values, which can be saved again", async ({ page, request }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await expect(showing(page, "Français")).toBeVisible()
	await expect(showing(page, "12h")).toBeVisible()
	await choose(page, "Français", "English")
	await choose(page, "12h", "24h")
	await saveButton(page).click()
	await expect(page.getByText("Settings saved successfully")).toBeVisible()
	const after = await system(request)
	expect([after.locale, after.timeFormat]).toEqual(["en-US", "24h"])
	watch.expectNone()
})
