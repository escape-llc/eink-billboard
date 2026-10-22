import { expect, test } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// The Comic Vine API data source holds the key (free, from Comic Vine's API page); the Comic Vine Covers source asks for a series, with a Test that says which one it matches.
test.beforeEach(async ({ page }) => stubMapTiles(page))

test("the Comic Vine settings link to where an API key is got, and the key is a password", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Providers" }).click()
	await page.getByRole("tabpanel").locator(".p-select").first().click()
	await page.getByRole("option", { name: "comicvine", exact: true }).click()
	const link = page.getByRole("link", { name: "Get a free API key" })
	await expect(link).toBeVisible()
	await expect(link).toHaveAttribute("href", "https://comicvine.gamespot.com/api/")
	await expect(link).toHaveAttribute("target", "_blank")
	await expect(link).toHaveAttribute("rel", /noopener/)
	await expect(page.getByRole("textbox", { name: "API Key", exact: true })).toHaveAttribute("type", "password")
	watch.expectNone()
})

test("a track of Comic Vine Covers asks for a series and its Test says what is wrong without a key", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/playlist")
	await page.getByRole("button", { name: "Add track" }).click()
	await page.locator(".track-editor .p-select").filter({ hasText: "Data Source" }).first().click()
	await page.getByRole("option").filter({ hasText: "Comic Vine Covers" }).first().click()
	const series = page.locator(".track-editor input[name=series]")
	await expect(series).toBeVisible()
	const test = page.getByRole("button", { name: "Test Series" })
	await expect(test).toBeDisabled()
	await series.fill("Weird Science")
	await expect(test).toBeEnabled()
	await test.click()
	// the device has no key saved: our words, no address and no site text
	await expect(page.getByText("The Comic Vine API key is not set. Add it in the Comic Vine settings.")).toBeVisible()
	watch.expectNone()
})
