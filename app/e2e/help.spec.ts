import { expect, test, type Locator, type Page } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// Every form (BasicForm) can hide the help under its fields from its header (HelpToggle): the settings tabs, a timer task, a playlist track.
test.beforeEach(async ({ page }) => stubMapTiles(page))

async function toggles(page: Page, scope: Locator) {
	const help = scope.locator(".field-help")
	const toggle = scope.getByRole("button", { name: "Help text" }).first()
	await expect(help.first()).toBeVisible()
	await expect(toggle).toHaveAttribute("aria-pressed", "true")
	await toggle.click()
	await expect(help).toHaveCount(0)
	await expect(toggle).toHaveAttribute("aria-pressed", "false")
	await toggle.click()
	await expect(help.first()).toBeVisible()
}

test("a settings form hides its help from its header", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Data Sources" }).click()
	await page.getByRole("tabpanel").locator(".p-select").first().click()
	await page.getByRole("option", { name: "weather", exact: true }).click()
	await toggles(page, page.getByRole("tabpanel"))
	watch.expectNone()
})

test("a timer task's form hides its help from its header", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/schedule")
	await page.getByRole("button", { name: "New task" }).click()
	await toggles(page, page.getByRole("dialog", { name: "New task" }))
	watch.expectNone()
})
