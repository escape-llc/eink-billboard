import { expect, test } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// A page that is waiting for the server shows that it is, and a request that fails says so: never an empty page (#33).
test.beforeEach(async ({ page }) => stubMapTiles(page))

const slow = async (page: import("@playwright/test").Page, pattern: string, ms: number) =>
	page.route(pattern, async route => { await new Promise(r => setTimeout(r, ms)); await route.continue() })

test("the playlist editor shows a loading bar until its lists are here", async ({ page }) => {
	const watch = watchProblems(page)
	await slow(page, "**/api/plugins/list", 800)
	await page.goto("/#/playlist")
	await expect(page.getByTestId("loading")).toBeVisible()
	await expect(page.getByTestId("loading")).toBeHidden()
	await expect(page.getByRole("button", { name: "New playlist" })).toBeVisible()
	watch.expectNone()
})

test("the scheduler shows a loading bar until the schedule is here", async ({ page }) => {
	const watch = watchProblems(page)
	await slow(page, "**/api/schedule/tasks/render*", 800)
	await page.goto("/#/schedule")
	await expect(page.getByTestId("loading")).toBeVisible()
	await expect(page.getByTestId("loading")).toBeHidden()
	watch.expectNone()
})

test("a plugin list that does not load is a message, not an empty editor", async ({ page }) => {
	const watch = watchProblems(page, [500], [/fetch\.pl\.unhandled/])
	await page.route("**/api/plugins/list", route => route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ success: false, message: "Something went wrong.", id: "x" }) }))
	await page.goto("/#/playlist")
	await expect(page.getByText("Failed to load the plugins")).toBeVisible()
	await expect(page.getByTestId("loading")).toBeHidden()
	watch.expectNone()
})
