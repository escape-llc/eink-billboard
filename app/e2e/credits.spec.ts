import { expect, test } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// Every credit is in one list (#534), the Help drawer's last section: the data the providers and data sources download, the fonts, the software and the artwork by others, and the project that inspired this one.
test.beforeEach(async ({ page }) => stubMapTiles(page))

test("the Help drawer's last section is the credits: the data, the fonts and the software", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/system")
	await page.getByRole("button", { name: "Help" }).click()
	const help = page.getByTestId("help")
	await expect(help.locator(".p-accordionheader").last()).toHaveText("Credits")
	await help.getByRole("button", { name: "Credits" }).click()
	const credits = help.getByTestId("credits")
	// a provider's credit is its descriptor's, a link to the service, with its licence
	await expect(credits.getByRole("link", { name: "Weather data by Open-Meteo.com" })).toHaveAttribute("href", "https://open-meteo.com/")
	await expect(credits.getByText("CC BY 4.0; free for non-commercial use")).toBeVisible()
	await expect(credits.getByText("Picture of the Day, Wikimedia Commons")).toBeVisible()
	// the fonts with their authors, and the software
	await expect(credits.getByText("Braille Institute of America")).toBeVisible()
	await expect(credits.getByText("Leaflet", { exact: true })).toBeVisible()
	await expect(credits.getByText("segno", { exact: true })).toBeVisible()
	// the clock's artwork, by its maker under CC BY, and the project that inspired this one
	await expect(credits.getByRole("heading", { name: "Artwork" })).toBeVisible()
	await expect(credits.getByRole("link", { name: "eScape Technology LLC" })).toHaveAttribute("href", "https://creativecommons.org/licenses/by/4.0/")
	await expect(credits.getByRole("heading", { name: "Inspiration" })).toBeVisible()
	await expect(credits.getByText("InkyPi", { exact: true })).toBeVisible()
	watch.expectNone()
})

test("the credits are asked for when their section is first opened, not with the drawer, and there is no page or menu entry of their own", async ({ page }) => {
	const watch = watchProblems(page)
	const asked: string[] = []
	page.on("request", r => { if (new URL(r.url()).pathname === "/api/credits") asked.push(r.url()) })
	await page.goto("/#/system")
	await page.locator("button[aria-controls=overlay_tmenu]").first().click()
	await expect(page.getByRole("menuitem", { name: "System" })).toBeVisible()
	await expect(page.getByRole("menuitem", { name: "Credits" })).toHaveCount(0)
	await page.keyboard.press("Escape")
	await page.getByRole("button", { name: "Help" }).click()
	const help = page.getByTestId("help")
	await expect(help.getByRole("button", { name: "First steps" })).toBeVisible()
	expect(asked).toEqual([])
	await help.getByRole("button", { name: "Credits" }).click()
	await expect(help.getByTestId("credits").getByText("Leaflet", { exact: true })).toBeVisible()
	// closed and opened again: kept, not asked again
	await help.getByRole("button", { name: "Credits" }).click()
	await help.getByRole("button", { name: "Credits" }).click()
	await expect(help.getByTestId("credits").getByText("Leaflet", { exact: true })).toBeVisible()
	expect(asked).toHaveLength(1)
	watch.expectNone()
})

test("the map picker credits OpenStreetMap on the map, as its tile policy asks", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await expect(page.locator(".leaflet-control-attribution").first()).toContainText("OpenStreetMap contributors")
	watch.expectNone()
})
