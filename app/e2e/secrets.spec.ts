import fs from "node:fs"
import path from "node:path"
import { expect, test, type Page } from "@playwright/test"
import { OPEN } from "./servers"
import { saveButton, stubMapTiles, watchProblems } from "./support"

// The fixture storage has a fake OpenAI key (the OpenAI provider's settings); the browser must only ever see the mask.
const KEY = "sk-fake-e2e-key-0000"
const NEW_KEY = "sk-fake-e2e-key-0001"
const MASK = "********"
const API = "/api/datasources/openai-api/settings"
const stored = () => JSON.parse(fs.readFileSync(path.join(OPEN.storage, "datasources", "openai-api", "settings.json"), "utf8")).apiKey

test.describe.configure({ mode: "serial" })
test.beforeEach(async ({ page }) => stubMapTiles(page))

async function openKeyForm(page: Page) {
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Providers" }).click()
	await page.getByRole("tabpanel").locator(".p-select").first().click()
	await page.getByRole("option", { name: "openai-api", exact: true }).click()
	return page.getByRole("tabpanel").locator("input[type=password]")
}

test("the API masks the stored key", async ({ request }) => {
	const rx = await request.get(API)
	const text = await rx.text()
	expect(text).not.toContain(KEY)
	expect(JSON.parse(text).apiKey).toBe(MASK)
})

test("the page shows a password field holding only the mask", async ({ page }) => {
	const watch = watchProblems(page)
	const response = page.waitForResponse(r => r.url().endsWith(API))
	const input = await openKeyForm(page)
	await expect(input).toHaveValue(MASK)
	expect(await (await response).text()).not.toContain(KEY)
	expect(await page.content()).not.toContain(KEY)
	watch.expectNone()
})

test("saving the untouched mask keeps the stored key", async ({ page }) => {
	const watch = watchProblems(page)
	const input = await openKeyForm(page)
	await expect(input).toHaveValue(MASK)
	// the mask alone is no change, so nothing is saved: another field changes and the mask goes back with it
	await expect(saveButton(page)).toBeDisabled()
	const days = page.getByRole("tabpanel").getByRole("spinbutton", { name: "Forget Unused Answers After (days)" })
	await days.fill("31")
	await days.blur()
	await saveButton(page).click()
	await expect(page.getByText("Settings saved successfully")).toBeVisible()
	expect(stored()).toBe(KEY)
	watch.expectNone()
})

test("a monthly quota can be set, shows its reset day, and is saved without touching the key", async ({ page }) => {
	const watch = watchProblems(page)
	const input = await openKeyForm(page)
	await expect(input).toHaveValue(MASK)
	// the reset day only matters once there is a quota
	await expect(page.getByRole("spinbutton", { name: "Quota Resets On (day of the month)" })).toHaveCount(0)
	const quota = page.getByRole("spinbutton", { name: "Monthly Quota (calls)" })
	await quota.fill("1000")
	await quota.blur()
	const day = page.getByRole("spinbutton", { name: "Quota Resets On (day of the month)" })
	await expect(day).toBeVisible()
	await day.fill("15")
	await day.blur()
	await saveButton(page).click()
	await expect(page.getByText("Settings saved successfully")).toBeVisible()
	expect(stored()).toBe(KEY)
	const saved = JSON.parse(fs.readFileSync(path.join(OPEN.storage, "datasources", "openai-api", "settings.json"), "utf8"))
	expect([saved.monthlyQuota, saved.quotaResetDay]).toEqual([1000, 15])
	watch.expectNone()
})

test("typing a new key replaces it", async ({ page, request }) => {
	const watch = watchProblems(page)
	const input = await openKeyForm(page)
	await input.fill(NEW_KEY)
	await saveButton(page).click()
	await expect(page.getByText("Settings saved successfully")).toBeVisible()
	expect(stored()).toBe(NEW_KEY)
	// and the API still only shows the mask
	expect(JSON.parse(await (await request.get(API)).text()).apiKey).toBe(MASK)
	watch.expectNone()
})
