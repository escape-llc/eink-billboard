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

test("a conflict offers Reload, which shows the server's copy and saves cleanly", async ({ page, request }) => {
	const watch = watchProblems(page, [409], [/Revision mismatch/])
	await page.goto("/#/settings")
	await expect(showing(page, "English")).toBeVisible()
	const doc = await system(request)
	expect((await request.put("/api/settings/system", { data: { ...doc, timeFormat: "12h" } })).ok()).toBe(true)

	await choose(page, "English", "Deutsch")
	await saveButton(page).click()
	await expect(page.getByText(/Revision mismatch/)).toBeVisible()
	await page.getByRole("button", { name: "Reload" }).click()
	await expect(page.getByText(/Revision mismatch/)).toBeHidden()
	// the page now shows what the server has (our Deutsch edit is gone, the other save's 12h is there)
	await expect(showing(page, "English")).toBeVisible()
	await expect(showing(page, "12h")).toBeVisible()
	await choose(page, "12h", "24h")
	await saveButton(page).click()
	await expect(page.getByText("Settings saved successfully")).toBeVisible()
	expect((await system(request)).timeFormat).toBe("24h")
	watch.expectNone()
})

test("a conflict offers Overwrite, which saves our edit over the other one", async ({ page, request }) => {
	const watch = watchProblems(page, [409], [/Revision mismatch/])
	await page.goto("/#/settings")
	await expect(showing(page, "English")).toBeVisible()
	const doc = await system(request)
	expect((await request.put("/api/settings/system", { data: { ...doc, timeFormat: "12h" } })).ok()).toBe(true)

	await choose(page, "English", "Deutsch")
	await saveButton(page).click()
	await page.getByRole("button", { name: "Overwrite" }).click()
	await expect(page.getByText("Settings saved successfully")).toBeVisible()
	const after = await system(request)
	expect(after.locale).toBe("de-DE")
	watch.expectNone()
})

test("a 422 from the server is shown on the field it names", async ({ page }) => {
	const watch = watchProblems(page, [422], [/422/])
	await page.route("**/api/settings/system", async route => {
		if (route.request().method() !== "PUT") return route.fallback()
		await route.fulfill({
			status: 422, contentType: "application/json",
			body: JSON.stringify({ success: false, message: "Settings validation failed", id: "system-settings",
				errors: [{ path: ["timezoneName"], message: "Unknown time zone" }] })
		})
	})
	await page.goto("/#/settings")
	await expect(showing(page, "Deutsch")).toBeVisible()
	await choose(page, "Deutsch", "English")
	await saveButton(page).click()
	await expect(page.getByText("Unknown time zone")).toBeVisible()
	watch.expectNone()
})

test("leaving with unsaved edits asks first; Stay keeps them, Discard leaves", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	// whatever the earlier tests left as the locale, change it to another one
	const locale = page.getByRole("combobox").nth(1)
	// until the settings load, the select shows its placeholder (the field's label)
	await expect(locale).not.toHaveAttribute("aria-label", "Locale")
	const current = (await locale.getAttribute("aria-label"))!
	const other = current === "Français" ? "Deutsch" : "Français"
	await choose(page, current, other)
	await page.evaluate(() => { location.hash = "#/schedule" })
	await expect(page.getByText("Leave this page and discard your changes?")).toBeVisible()
	await page.getByRole("button", { name: "Stay" }).click()
	await expect(page).toHaveURL(/#\/settings/)
	await expect(showing(page, other)).toBeVisible()
	await page.evaluate(() => { location.hash = "#/schedule" })
	await page.getByRole("button", { name: "Discard" }).click()
	await expect(page).toHaveURL(/#\/schedule/)
	watch.expectNone()
})
