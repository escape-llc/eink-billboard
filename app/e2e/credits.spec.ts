import { expect, test } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// Every credit is on one page (#534): the data the providers and data sources download, the fonts and the software by others. The Help drawer leads there.
test.beforeEach(async ({ page }) => stubMapTiles(page))

test("the Help drawer leads to the Credits page, which lists the data, the fonts and the software", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/system")
	await page.getByRole("button", { name: "Help" }).click()
	const help = page.getByTestId("help")
	await help.getByRole("button", { name: "More" }).click()
	await help.getByRole("link", { name: "Credits" }).click()
	await expect(page).toHaveURL(/#\/credits$/)
	await expect(help).toBeHidden()
	const credits = page.getByTestId("credits")
	// a provider's credit is its descriptor's, a link to the service, with its licence
	await expect(credits.getByRole("link", { name: "Weather data by Open-Meteo.com" })).toHaveAttribute("href", "https://open-meteo.com/")
	await expect(credits.getByText("CC BY 4.0; free for non-commercial use")).toBeVisible()
	await expect(credits.getByText("Picture of the Day, Wikimedia Commons")).toBeVisible()
	// the fonts with their authors, and the software
	await expect(credits.getByText("Braille Institute of America")).toBeVisible()
	await expect(credits.getByText("Leaflet", { exact: true })).toBeVisible()
	watch.expectNone()
})

test("the Credits page is in the menu", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/system")
	await page.locator("button[aria-controls=overlay_tmenu]").first().click()
	await page.getByRole("menuitem", { name: "Credits" }).click()
	await expect(page.getByTestId("credits").getByRole("heading", { name: "Fonts" })).toBeVisible()
	watch.expectNone()
})

test("the map picker credits OpenStreetMap on the map, as its tile policy asks", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await expect(page.locator(".leaflet-control-attribution").first()).toContainText("OpenStreetMap contributors")
	watch.expectNone()
})
