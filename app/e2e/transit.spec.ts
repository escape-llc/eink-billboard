import { expect, test, type Page } from "@playwright/test"
import { watchProblems } from "./support"

// Transitland's My Stops (#429): a row's Stop is chosen from the stops near the device, a URL lookup of the provider's own, or found with the row's search box
// (the stop finder). The test servers have no key and must not reach Transitland, so the list is answered here, in the browser (the route itself, and its kept
// answers, are test_transitland's).
const NEARBY = [
	{ name: "Main St & 3rd Ave, Northbound (40 m)", value: "s-c23nb-mainst~3rd" },
	{ name: "Main St & 3rd Ave, Southbound (210 m)", value: "s-c23nb-mainst~3rd~sb" },
]
const FOUND = [{ name: "Harbor Ferry Terminal, Pier 2 (5.2 km)", value: "s-c23p3-harborferry" }]

async function answerStops(page: Page): Promise<string[]> {
	const asked: string[] = []
	await page.route(/\/api\/datasource\/transitland-api\/lookups\/stops(\?.*)?$/, route => {
		const q = new URL(route.request().url()).searchParams.get("q")
		asked.push(q ?? "")
		return route.fulfill({ json: q === null || q === "" ? NEARBY : q === "s-c23p3-harborferry" || /harbor/i.test(q) ? FOUND : [] })
	})
	return asked
}

async function openMyStops(page: Page) {
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Providers" }).click()
	await page.locator(".p-select").last().click()
	await page.getByRole("option").filter({ hasText: "transitland-api" }).click()
}

test("a stop of My Stops is chosen from the stops near the device", async ({ page }) => {
	const watch = watchProblems(page)
	await answerStops(page)
	await openMyStops(page)
	// the provider says what uses it: the Departure Board
	await expect(page.getByText("Used by")).toBeVisible()
	await page.getByRole("button", { name: "Add" }).first().click()
	await page.getByRole("combobox", { name: "Stop 1" }).click()
	await expect(page.getByRole("option")).toHaveText(NEARBY.map(s => s.name))
	await page.getByRole("option", { name: /Southbound/ }).click()
	await expect(page.getByRole("combobox", { name: "Stop 1" })).toContainText("Southbound")
	watch.expectNone()
})

test("a stop beyond the nearby list is found by its name in the row's search box", async ({ page }) => {
	const watch = watchProblems(page)
	const asked = await answerStops(page)
	await openMyStops(page)
	await page.getByRole("button", { name: "Add" }).first().click()
	// a search that finds nothing says so; the text goes only on Enter or Search, never per keystroke
	await page.getByRole("textbox", { name: "Search Stop 1" }).fill("zzz")
	await page.getByRole("button", { name: "Search for Stop 1" }).click()
	await expect(page.getByText('Nothing found for "zzz".')).toBeVisible()
	await page.getByRole("textbox", { name: "Search Stop 1" }).fill("harbor")
	await page.getByRole("textbox", { name: "Search Stop 1" }).press("Enter")
	await page.getByRole("combobox", { name: "Stop 1" }).click()
	await expect(page.getByRole("option")).toHaveText(FOUND.map(s => s.name))
	await page.getByRole("option", { name: /Harbor Ferry/ }).click()
	await expect(page.getByRole("combobox", { name: "Stop 1" })).toContainText("Harbor Ferry Terminal")
	// a stop a search found is good, though the stops near the device do not list it
	await expect(page.getByText("Not one of the allowed values")).toHaveCount(0)
	expect(asked).not.toContain("z")
	expect(asked).toEqual(expect.arrayContaining(["", "zzz", "harbor"]))
	watch.expectNone()
})

test("a stored stop the nearby list lacks is asked for by its key, so it shows its name", async ({ page }) => {
	const watch = watchProblems(page)
	const asked = await answerStops(page)
	// the stored settings hold a stop a search found once (answered here: the run's storage is shared by the tests)
	await page.route("**/api/datasources/transitland-api/settings", async route => {
		if (route.request().method() !== "GET") return route.continue()
		const stored = await (await route.fetch()).json()
		return route.fulfill({ json: { ...stored, stops: [{ name: "Ferry", stopKey: "s-c23p3-harborferry", walkMinutes: 5, routes: null }] } })
	})
	await openMyStops(page)
	await expect(page.getByRole("combobox", { name: "Stop 1" })).toContainText("Harbor Ferry Terminal")
	await expect(page.getByText("Not one of the allowed values")).toHaveCount(0)
	// asked once the nearby list had answered without it, and only then
	expect(asked).toEqual(["", "s-c23p3-harborferry"])
	watch.expectNone()
})

test("a row whose stops cannot be listed says why, not just an empty list (#816)", async ({ page }) => {
	// no routing: the test servers have no Transitland key, so the real lookup refuses, in our words
	await openMyStops(page)
	await page.getByRole("button", { name: "Add" }).first().click()
	await expect(page.getByText(/The choices could not be loaded: (Enter the Transitland API key|Set the device's location first)/)).toBeVisible()
})
