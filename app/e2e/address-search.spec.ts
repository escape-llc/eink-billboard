import { expect, test } from "@playwright/test"
import { stubAddressSearch, stubMapTiles, watchProblems } from "./support"

// The location picker searches only when asked, never as you type (Nominatim's usage policy, #537): Search or Enter, one at a time, kept.
test.beforeEach(async ({ page }) => stubMapTiles(page))

test("typing sends nothing; Enter searches, a result sets the location, and the same text again is not asked twice", async ({ page }) => {
	const watch = watchProblems(page)
	const queries = await stubAddressSearch(page)
	const writes: string[] = []
	page.on("request", r => { if (["PUT", "PATCH"].includes(r.method())) writes.push(`${r.method()} ${r.url()}`) })
	await page.goto("/#/settings")
	const address = page.getByRole("textbox", { name: "Address" }).first()
	await address.pressSequentially("Big Ben London", { delay: 50 })
	// AutoComplete asked about 300 ms after a keystroke: wait well past that
	await page.waitForTimeout(800)
	expect(queries).toEqual([])
	await address.press("Enter")
	const results = page.getByTestId("address-results")
	await expect(results.getByRole("button", { name: /Big Ben/ })).toBeVisible()
	await expect(results).toContainText("OpenStreetMap contributors")
	expect(queries).toEqual(["Big Ben London"])
	await results.getByRole("button", { name: /Big Ben/ }).click()
	await expect(results).toBeHidden()
	await expect(page.getByText("51.5007N, 0.1246W")).toBeVisible()
	await address.press("Enter")
	await expect(results).toBeVisible()
	expect(queries).toEqual(["Big Ben London"])
	// Enter searches; it does not submit the settings form around the picker (a save is a PUT)
	expect(writes).toEqual([])
	watch.expectNone()
})

test("two quick presses of Search send one request", async ({ page }) => {
	const watch = watchProblems(page)
	const queries = await stubAddressSearch(page)
	await page.goto("/#/settings")
	await page.getByRole("textbox", { name: "Address" }).first().fill("Westminster")
	const searchButton = page.getByRole("button", { name: "Search", exact: true }).first()
	await searchButton.dblclick()
	await expect(page.getByTestId("address-results").getByRole("button", { name: /Big Ben/ })).toBeVisible()
	await searchButton.click()
	expect(queries).toEqual(["Westminster"])
	watch.expectNone()
})

test("a search that finds nothing says so", async ({ page }) => {
	const watch = watchProblems(page)
	await stubAddressSearch(page, [])
	await page.goto("/#/settings")
	await page.getByRole("textbox", { name: "Address" }).first().fill("Nowhere at all")
	await page.getByRole("button", { name: "Search", exact: true }).first().click()
	await expect(page.getByTestId("address-results")).toContainText("No place found")
	watch.expectNone()
})
