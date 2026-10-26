import { expect, test } from "@playwright/test"
import { choose, stubMapTiles, watchProblems } from "./support"

// The Display Type is a `schema` field (#397): it offers the installed display devices, and the chosen one's own fields appear under it, as a plugin's data source's do.
// Nothing is saved: the open server's display settings stay as the other specs expect.
test.beforeEach(async ({ page }) => stubMapTiles(page))

test("the display type offers the installed devices and shows the chosen one's fields", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Display" }).click()
	// the factory display is the mock: its size, its folder, its clean-up switch
	await expect(page.locator("input[name=width]")).toHaveValue("800")
	await expect(page.locator("input[name=height]")).toHaveValue("480")
	await expect(page.locator("input[name=outputFolder]")).toBeVisible()
	await expect(page.getByText("Border Color").first()).toHaveCount(0)
	// an Inky has a border color of its own and none of the mock's fields
	await choose(page, "Mock", "Inky")
	await expect(page.getByText("Border Color").first()).toBeVisible()
	await expect(page.locator("input[name=width]")).toHaveCount(0)
	await expect(page.locator("input[name=outputFolder]")).toHaveCount(0)
	// a Waveshare must be told its model
	await choose(page, "Inky", "Waveshare")
	await expect(page.getByText("Waveshare Model", { exact: true })).toBeVisible()
	await expect(page.getByText("Border Color").first()).toHaveCount(0)
	watch.expectNone()
})
