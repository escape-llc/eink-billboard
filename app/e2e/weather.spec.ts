import { expect, test } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// The Weather data source's key comes from a page of OpenWeatherMap's: its settings carry a link to it (a descriptor's `link`).
test.beforeEach(async ({ page }) => stubMapTiles(page))

test("the weather settings link to where an API key is got, and the key is a password", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Data Sources" }).click()
	await page.getByRole("tabpanel").locator(".p-select").first().click()
	await page.getByRole("option", { name: /^weather/i }).click()
	const link = page.getByRole("link", { name: "Get a free API key" })
	await expect(link).toBeVisible()
	await expect(link).toHaveAttribute("href", "https://home.openweathermap.org/users/sign_up")
	await expect(link).toHaveAttribute("target", "_blank")
	await expect(link).toHaveAttribute("rel", /noopener/)
	await expect(page.getByRole("textbox", { name: "API Key", exact: true })).toHaveAttribute("type", "password")
	watch.expectNone()
})
