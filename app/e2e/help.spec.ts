import { expect, test } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// The Help button (it was a cog that went nowhere) opens a drawer that slides out over the page with a short guide, and closes again; the page under it is not left.
test.beforeEach(async ({ page }) => stubMapTiles(page))

test("the Help button opens a drawer over the page, with the guide in it, and it closes", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/system")
	await expect(page.getByRole("complementary").or(page.getByTestId("help"))).toHaveCount(0)
	await page.getByRole("button", { name: "Help" }).click()
	const help = page.getByTestId("help")
	await expect(help).toBeVisible()
	await expect(help.getByText("First steps")).toBeVisible()
	// the first section is open; another opens on a click
	await expect(help.getByText("Settings, System:")).toBeVisible()
	await help.getByRole("button", { name: "The pages" }).click()
	await expect(help.getByText("Timer tasks:")).toBeVisible()
	// the build is the one in the header
	await help.getByRole("button", { name: "When something is wrong" }).click()
	await expect(help.getByText(/^v\S+ \(\S+\)$/)).toBeVisible()
	// the page under it is still the System page
	expect(page.url()).toContain("#/system")
	await page.keyboard.press("Escape")
	await expect(help).toBeHidden()
	watch.expectNone()
})
