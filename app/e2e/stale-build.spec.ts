import { expect, test } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// A tab opened before an update runs the old build: the next page it opens asks for a chunk the update replaced (a 404). It reloads itself, once,
// at the page it was going to, and the reload is the new build.
test("a page of an old build that is gone reloads the tab once, at that page", async ({ page }) => {
	await stubMapTiles(page)
	const watch = watchProblems(page, [404], [/dynamically imported module|404/i])
	let loads = 0
	page.on("load", () => { loads++ })
	await page.goto("/#/schedule")
	await expect(page.getByRole("button", { name: "New task" })).toBeVisible()
	// as after an update: the Settings page's chunk of this build is gone (the server answers 404 for a missing bundle; Vite preloads it, then
	// imports it: both are refused) until the tab loads the page again, which is the new build
	let refused = 0
	let reloaded = false
	page.on("request", r => { if (r.resourceType() === "document" && loads >= 1) reloaded = true })
	await page.route(/\/assets\/Settings-[^/]+\.js$/, route => {
		if (reloaded) return route.continue()
		refused++
		return route.fulfill({ status: 404, contentType: "application/json", body: "{\"success\":false}" })
	})
	await page.getByRole("button", { name: "Menu" }).or(page.locator("button[aria-controls=overlay_tmenu]").first()).first().click()
	await page.getByRole("menuitem", { name: "Settings" }).click()
	await expect(page.getByText("System Settings")).toBeVisible()
	expect(refused, "the old build's chunk was refused").toBeGreaterThan(0)
	expect(loads, "the first load and one reload").toBe(2)
	expect(new URL(page.url()).hash).toBe("#/settings")
	watch.expectNone()
})
