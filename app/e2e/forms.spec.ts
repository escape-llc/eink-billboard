import { expect, test } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

test.beforeEach(async ({ page }) => stubMapTiles(page))

// the row a form field renders into: its label plus the control(s)
const row = (page: import("@playwright/test").Page, label: string) =>
	page.locator(".p-inputgroup").filter({ has: page.locator("label", { hasText: label }) })

test("a boolean field is one toggle, not a toggle followed by a text box", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Display" }).click()
	const rotate = row(page, "Rotate 180")
	await expect(rotate).toHaveCount(1)
	await expect(rotate.locator(".p-toggleswitch")).toHaveCount(1)
	await expect(rotate.locator("input[type=text]")).toHaveCount(0)
	watch.expectNone()
})

test("a field shown only when another is on: hidden until then, required while shown, saved as null when hidden again", async ({ page, request }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Display" }).click()
	const detail = page.getByPlaceholder("E2E Detail")
	const save = page.getByRole("tabpanel").locator("button:has(.pi-check)").first()
	const toggle = row(page, "E2E Advanced").locator(".p-toggleswitch")
	await expect(toggle).toBeVisible()
	await expect(detail).toHaveCount(0)

	await toggle.click()
	await expect(detail).toBeVisible()
	// shown and required, so empty is invalid and the form does not save
	await detail.focus()
	await detail.blur()
	await expect(page.getByText("Required")).toBeVisible()
	await detail.fill("some detail")
	await expect(save).toBeEnabled()
	await save.click()
	await expect(page.getByText("Settings saved successfully")).toBeVisible()
	expect((await (await request.get("/api/settings/display")).json()).e2eDetail).toBe("some detail")

	// hidden again: no longer required, and what it held is not kept
	await toggle.click()
	await expect(detail).toHaveCount(0)
	await expect(save).toBeEnabled()
	await save.click()
	const display = async () => (await request.get("/api/settings/display")).json()
	await expect.poll(async () => (await display()).e2eAdvanced).toBe(false)
	expect((await display()).e2eDetail).toBeNull()
	watch.expectNone()
})

test("the playlist track form renders the plugin's fields and follows a change of plugin", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/playlist")
	await page.getByText("Morning slides").first().click()
	const editor = page.locator(".track-editor")
	// a form that failed to build would be an empty card
	await expect(editor.locator("label", { hasText: "Title" })).toBeVisible()
	await expect(editor.locator("label", { hasText: "Max Slides" })).toBeVisible()
	await expect(editor.getByRole("spinbutton").first()).toBeVisible()

	// the plugin is the form's own field list: another plugin brings its own fields
	await editor.locator(".p-select").filter({ hasText: "Slide Show" }).first().click()
	await page.getByRole("option").filter({ hasText: "Interstitial Overlay" }).first().click()
	await expect(editor.locator("label", { hasText: "Max Slides" })).toHaveCount(0)
	await expect(editor.locator("label", { hasText: "Slide Duration" })).toBeVisible()
	watch.expectNone()
})
