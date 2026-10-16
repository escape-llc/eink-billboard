import { expect, test } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// The Plugins and the Data Sources tabs show a descriptor the same way: one attribute to a row, label then value.
test.beforeEach(async ({ page }) => stubMapTiles(page))

test("a data source's descriptor is a table of attributes, with what it uses and what it can do", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Data Sources" }).click()
	await page.getByRole("tabpanel").locator(".p-select").first().click()
	await page.getByRole("option", { name: "weather-overlay", exact: true }).click()
	const info = page.getByTestId("item-info")
	await expect(info).toBeVisible()
	await expect(page.getByTestId("info-id")).toHaveText("weather-overlay")
	await expect(page.getByTestId("info-enabled").getByRole("img", { name: "yes" })).toBeVisible()
	// it asks an API source for the weather: it says so, and names it; it downloads nothing itself
	await expect(page.getByTestId("info-uses")).toContainText("openweathermap")
	const features = page.getByTestId("info-features")
	await expect(features).toContainText("api-client")
	await expect(features).toContainText("layer-overlay")
	await expect(features).not.toContainText("internet")
	await expect(features.locator(".p-tag", { hasText: "api-client" })).toHaveAttribute("title", /Asks an API data source/)
	await expect(page.getByTestId("info-shown-as")).toContainText("{")
	// the labels are a column of their own: attributes are rows
	const labels = await info.locator("dt").allTextContents()
	expect(labels).toEqual(["Name", "Id", "Version", "Enabled", "Description", "Features", "Uses", "Keeps its list", "Shown as"])
	watch.expectNone()
})

test("the plugins tab shows the same table, without the rows that are only a data source's", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Plugins" }).click()
	await page.getByRole("tabpanel").locator(".p-select").first().click()
	await page.getByRole("option", { name: "slide-show", exact: true }).click()
	const info = page.getByTestId("item-info")
	await expect(page.getByTestId("info-id")).toHaveText("slide-show")
	await expect(page.getByTestId("info-features")).toContainText("layer-background")
	expect(await info.locator("dt").allTextContents()).toEqual(["Name", "Id", "Version", "Enabled", "Description", "Features", "Shown as"])
	watch.expectNone()
})
