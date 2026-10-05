import fs from "node:fs"
import path from "node:path"
import { expect, test, type Page } from "@playwright/test"
import { OPEN } from "./servers"
import { saveButton, stubMapTiles, watchProblems } from "./support"

// The fixture storage has a fake OpenAI key; the browser must only ever see the mask.
const KEY = "sk-fake-e2e-key-0000"
const NEW_KEY = "sk-fake-e2e-key-0001"
const MASK = "********"
const API = "/api/datasources/openai-image/settings"
const stored = () => JSON.parse(fs.readFileSync(path.join(OPEN.storage, "datasources", "openai-image", "settings.json"), "utf8")).apiKey

test.describe.configure({ mode: "serial" })
test.beforeEach(async ({ page }) => stubMapTiles(page))

async function openKeyForm(page: Page) {
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Data Sources" }).click()
	await page.getByRole("tabpanel").locator(".p-select").first().click()
	await page.getByRole("option").filter({ hasText: "openai-image" }).click()
	return page.locator("input[type=password]")
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
	// retyping the same value is what makes the form valid and enables the save button
	await input.fill(MASK)
	await saveButton(page).click()
	await expect(page.getByText("Settings saved successfully")).toBeVisible()
	expect(stored()).toBe(KEY)
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
