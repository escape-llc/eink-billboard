import { expect, test, type APIRequestContext, type Page } from "@playwright/test"
import { choose, saveButton, stubMapTiles, watchProblems } from "./support"

// These tests change the settings of the shared server, one after the other.
test.describe.configure({ mode: "serial" })
const system = async (request: APIRequestContext) => (await request.get("/api/settings/system")).json()
test.beforeEach(async ({ page }) => stubMapTiles(page))

// and put them back after, so the specs after these (the phone project's, run on the same server) find the settings they started with
let before: Record<string, unknown> | undefined
test.beforeAll(async ({ request }) => { before = await system(request) })
test.afterAll(async ({ request }) => {
	if (before === undefined) return
	const { _rev } = await system(request)
	expect((await request.put("/api/settings/system", { data: { ...before, _rev } })).ok()).toBe(true)
})

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
	// somebody else changes the settings while this page has an edit (without one, the page would show theirs)
	await choose(page, "Français", "Deutsch")
	const doc = await system(request)
	const put = await request.put("/api/settings/system", { data: { ...doc, timeFormat: "12h" } })
	expect(put.ok()).toBe(true)

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
	await choose(page, "English", "Deutsch")
	const doc = await system(request)
	expect((await request.put("/api/settings/system", { data: { ...doc, timeFormat: "12h" } })).ok()).toBe(true)

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
	await choose(page, "English", "Deutsch")
	const doc = await system(request)
	expect((await request.put("/api/settings/system", { data: { ...doc, timeFormat: "12h" } })).ok()).toBe(true)

	await saveButton(page).click()
	await page.getByRole("button", { name: "Overwrite" }).click()
	await expect(page.getByText("Settings saved successfully")).toBeVisible()
	const after = await system(request)
	expect(after.locale).toBe("de-DE")
	watch.expectNone()
})

// a save from another tab (the device's command line and a restore are the same to the page: the watcher reports the stored file)
const LOCALES: Record<string, string> = { "en-US": "English", "fr-FR": "Français", "de-DE": "Deutsch" }
/** Another tab saves the system settings with another locale; answers the locale's label. */
async function savedElsewhere(page: Page, request: APIRequestContext): Promise<string> {
	const other = await page.context().newPage()
	const watch = watchProblems(other)
	const current = LOCALES[(await system(request)).locale]!
	const next = current === "Deutsch" ? "English" : "Deutsch"
	await other.goto("/#/settings")
	await expect(showing(other, current)).toBeVisible()
	await choose(other, current, next)
	await saveButton(other).click()
	await expect(other.getByText("Settings saved successfully")).toBeVisible()
	watch.expectNone()
	await other.close()
	return next
}
async function openSettings(page: Page, request: APIRequestContext) {
	await page.goto("/#/settings")
	const { locale, timeFormat } = await system(request)
	await expect(showing(page, LOCALES[locale]!)).toBeVisible()
	// a reload would forget this
	await page.evaluate(() => { (window as unknown as { stayed: boolean }).stayed = true })
	return { locale: LOCALES[locale]!, timeFormat: String(timeFormat) }
}
const stayed = (page: Page) => page.evaluate(() => (window as unknown as { stayed?: boolean }).stayed)
const banner = (page: Page) => page.locator(".changed-elsewhere")

test("settings saved in another tab are shown in an open page that has no edits", async ({ page, request }) => {
	const watch = watchProblems(page)
	await openSettings(page, request)
	const next = await savedElsewhere(page, request)
	await expect(showing(page, next)).toBeVisible({ timeout: 15_000 })
	await expect(banner(page)).toBeHidden()
	expect(await stayed(page)).toBe(true)
	// what it shows is the stored document: nothing is unsaved, and a save goes over the new revision
	await page.evaluate(() => { location.hash = "#/schedule" })
	await expect(page).toHaveURL(/#\/schedule/)
	watch.expectNone()
})

test("with edits, a save elsewhere says so; Reload shows theirs", async ({ page, request }) => {
	const watch = watchProblems(page)
	const opened = await openSettings(page, request)
	const mine = opened.timeFormat === "12h" ? "24h" : "12h"
	await choose(page, opened.timeFormat, mine)
	const theirs = await savedElsewhere(page, request)
	await expect(banner(page)).toContainText("Changed elsewhere", { timeout: 15_000 })
	// the edit is still there until the person decides
	await expect(showing(page, mine)).toBeVisible()
	await banner(page).getByRole("button", { name: "Reload" }).click()
	await expect(banner(page)).toBeHidden()
	await expect(showing(page, theirs)).toBeVisible()
	await expect(showing(page, opened.timeFormat)).toBeVisible()
	expect(await stayed(page)).toBe(true)
	await page.evaluate(() => { location.hash = "#/schedule" })
	await expect(page).toHaveURL(/#\/schedule/)
	watch.expectNone()
})

test("with edits, Keep editing keeps them; saving asks whether to overwrite the other save", async ({ page, request }) => {
	const watch = watchProblems(page, [409], [/Revision mismatch/])
	const opened = await openSettings(page, request)
	const mine = opened.timeFormat === "12h" ? "24h" : "12h"
	await choose(page, opened.timeFormat, mine)
	const theirs = await savedElsewhere(page, request)
	await expect(banner(page)).toBeVisible({ timeout: 15_000 })
	await banner(page).getByRole("button", { name: "Keep editing" }).click()
	await expect(banner(page)).toBeHidden()
	await expect(showing(page, mine)).toBeVisible()
	await saveButton(page).click()
	await expect(page.getByText(/Revision mismatch/)).toBeVisible()
	await page.getByRole("button", { name: "Overwrite" }).click()
	await expect(page.getByText("Settings saved successfully")).toBeVisible()
	// mine is what the page sent: every field it holds, so the other tab's locale is replaced by the one this page loaded
	const after = await system(request)
	expect([LOCALES[after.locale], after.timeFormat]).toEqual([opened.locale, mine])
	expect(theirs).not.toBe(opened.locale)
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

test("an edit that is put back is not unsaved: leaving does not ask", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	const locale = page.getByRole("combobox").nth(1)
	await expect(locale).not.toHaveAttribute("aria-label", "Locale")
	const current = (await locale.getAttribute("aria-label"))!
	const other = current === "Français" ? "Deutsch" : "Français"
	await choose(page, current, other)
	await choose(page, other, current)
	await page.evaluate(() => { location.hash = "#/schedule" })
	await expect(page).toHaveURL(/#\/schedule/)
	await expect(page.getByText("Leave this page and discard your changes?")).toBeHidden()
	watch.expectNone()
})

test("a settings form that only opened is not unsaved, whatever it filled in itself", async ({ page }) => {
	const watch = watchProblems(page)
	// each tab's form, and an item's settings on the item tabs (the calendar's rows hold secrets and choices; a form fills defaults and masks as it opens)
	const forms: [string, string | null][] = [["System", null], ["Display", null], ["Theme", null], ["Master Prompts", null], ["Devices", null],
		["Plugins", "slide-show"], ["Data Sources", "image-folder"], ["Providers", "calendar-sources"], ["Providers", "openai-api"]]
	for (const [tab, item] of forms) {
		await page.goto("/#/settings")
		await page.getByRole("tab", { name: tab }).click()
		if (item) {
			await page.getByRole("tabpanel").locator(".p-select").first().click()
			await page.getByRole("option", { name: item, exact: true }).click()
		}
		await expect(saveButton(page)).toBeVisible()
		await page.waitForLoadState("networkidle")
		await page.evaluate(() => { location.hash = "#/schedule" })
		await expect(page, `${tab} ${item ?? ""}`).toHaveURL(/#\/schedule/)
	}
	await expect(page.getByText("Leave this page and discard your changes?")).toBeHidden()
	watch.expectNone()
})

test("the weather provider is chosen from the providers of the weather, which say whether they are set up", async ({ page, request }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await expect(page.locator("#weatherProvider")).toBeVisible()
	expect((await system(request)).weatherProvider).toBeNull()
	await page.locator("#weatherProvider").click()
	const options = page.getByRole("listbox")
	// Open-Meteo needs no key; the test storage has no OpenWeatherMap key: it is offered, and says it is not set up (choosing it is harmless)
	await expect(options.getByRole("option")).toHaveText(["Open-Meteo", "OpenWeatherMap (not set up)"])
	await options.getByRole("option").filter({ hasText: "OpenWeatherMap" }).click()
	await saveButton(page).click()
	await expect(page.getByText("Settings saved successfully")).toBeVisible()
	expect((await system(request)).weatherProvider).toBe("openweathermap-api")
	// back to empty for the tests after this one
	const doc = await system(request)
	expect((await request.put("/api/settings/system", { data: { ...doc, weatherProvider: null } })).ok()).toBe(true)
	watch.expectNone()
})

test("the units are the device's: a master choice, and a kind of measurement may have its own", async ({ page, request }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await expect(page.locator("#speedUnit")).toBeVisible()
	expect((await system(request)).units).toBe("auto")
	await page.locator("#units").click()
	await page.getByRole("listbox").getByRole("option").filter({ hasText: "Metric (°C, km/h)" }).click()
	await page.locator("#speedUnit").click()
	await expect(page.getByRole("listbox").getByRole("option")).toHaveText(["Kilometres per hour (km/h)", "Metres per second (m/s)", "Miles per hour (mph)", "Knots (kn)"])
	await page.getByRole("listbox").getByRole("option").filter({ hasText: "Miles per hour" }).click()
	await saveButton(page).click()
	await expect(page.getByText("Settings saved successfully")).toBeVisible()
	const saved = await system(request)
	expect([saved.units, saved.temperatureUnit, saved.speedUnit]).toEqual(["metric", null, "mph"])
	// back as it was for the tests after this one
	expect((await request.put("/api/settings/system", { data: { ...saved, units: "auto", speedUnit: null } })).ok()).toBe(true)
	watch.expectNone()
})
