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
	// how to use a data source is here, not in the readme: the calendar sign-ins
	await help.getByRole("button", { name: "Calendars" }).click()
	await expect(help.getByText("Calendars.Read")).toBeVisible()
	// each provider is explained once, apart from the data sources that ask it
	await help.getByRole("button", { name: "Providers: where the data comes from" }).click()
	await expect(help.getByText("Calendar Sources", { exact: true })).toBeVisible()
	// every plugin and data source has its entry
	await help.getByRole("button", { name: "Sources: pictures" }).click()
	await expect(help.getByText("Image from a Web Address")).toBeVisible()
	// the build is the one in the header
	await help.getByRole("button", { name: "When something is wrong" }).click()
	await expect(help.getByText(/^v\S+ \(\S+\)$/)).toBeVisible()
	// the page under it is still the System page
	expect(page.url()).toContain("#/system")
	await page.keyboard.press("Escape")
	await expect(help).toBeHidden()
	watch.expectNone()
})

test("the header's build opens About: the project, its blog and the donate link (#824)", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/system")
	await page.getByTestId("app-version").click()
	const about = page.getByTestId("help-about")
	await expect(about.getByText("by eScape Technology LLC")).toBeVisible()
	// no Online Help: the old wiki is another application's
	await expect(about.getByRole("link", { name: "Online Help" })).toHaveCount(0)
	await expect(about.getByRole("link", { name: "Blog" })).toHaveAttribute("target", "_blank")
	await expect(about.getByRole("link", { name: "Donate with PayPal" })).toHaveAttribute("href", /paypal\.com\/donate/)
	// the Help button opens the drawer as it was left, not at About
	await page.keyboard.press("Escape")
	await page.getByRole("button", { name: "Help" }).click()
	await expect(page.getByTestId("help").getByText("Settings, System:")).toBeVisible()
	watch.expectNone()
})
