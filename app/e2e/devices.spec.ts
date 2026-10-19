import { expect, test } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// The Devices tab holds the pins of what is connected to the Pi (push buttons for now). Nothing here is saved: the open server's settings stay as the other specs expect.
test.beforeEach(async ({ page }) => stubMapTiles(page))

test("the devices tab offers the three buttons, empty, and keeps a pin on the header", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Devices" }).click()
	for (const name of ["buttonPlayStop", "buttonNext", "buttonStop"]) {
		await expect(page.locator(`input[name=${name}]`)).toBeVisible()
		await expect(page.locator(`input[name=${name}]`)).toHaveValue("")
	}
	await expect(page.getByText("Play / Stop Button")).toBeVisible()
	await expect(page.getByText("Next Button")).toBeVisible()
	// a pin must be a GPIO number of the header (2 to 27): the number field keeps what is typed inside that
	const next = page.locator("input[name=buttonNext]")
	await next.fill("40")
	await next.blur()
	await expect(next).toHaveValue("27")
	await next.fill("1")
	await next.blur()
	await expect(next).toHaveValue("2")
	watch.expectNone()
})
