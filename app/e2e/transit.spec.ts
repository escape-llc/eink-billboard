import { expect, test } from "@playwright/test"
import { watchProblems } from "./support"

// Transitland's My Stops (#429): a row's Stop is chosen from the stops near the device, a URL lookup of the provider's own. The test servers have no key and must not
// reach Transitland, so the list is answered here, in the browser (the route itself, and its kept answer, are test_transitland's).
test("a stop of My Stops is chosen from the stops near the device", async ({ page }) => {
	const watch = watchProblems(page)
	await page.route("**/api/datasource/transitland-api/lookups/stops", route => route.fulfill({ json: [
		{ name: "Main St & 3rd Ave, Northbound (40 m)", value: "s-c23nb-mainst~3rd" },
		{ name: "Main St & 3rd Ave, Southbound (210 m)", value: "s-c23nb-mainst~3rd~sb" },
	] }))
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Providers" }).click()
	await page.locator(".p-select").last().click()
	await page.getByRole("option").filter({ hasText: "transitland-api" }).click()
	// the provider says what uses it: the Departure Board
	await expect(page.getByText("Used by")).toBeVisible()
	await page.getByRole("button", { name: "Add" }).first().click()
	await page.getByRole("combobox", { name: "Stop 1" }).click()
	await expect(page.getByRole("option")).toHaveText(["Main St & 3rd Ave, Northbound (40 m)", "Main St & 3rd Ave, Southbound (210 m)"])
	await page.getByRole("option", { name: /Southbound/ }).click()
	await expect(page.getByRole("combobox", { name: "Stop 1" })).toContainText("Southbound")
	watch.expectNone()
})
