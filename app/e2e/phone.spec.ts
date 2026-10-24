import { expect, test, type Page } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// On a phone (#510 A5) every view fits the width of the screen: nothing scrolls sideways, neither the page nor the view's own area.
// It runs on the desktop project too, where it must hold as well.

/** How far each part that could scroll sideways is wider than its box, in CSS pixels (0 when it fits). */
async function overflow(page: Page) {
	return page.evaluate(() => {
		const wider = (e: Element | null) => e ? Math.max(0, e.scrollWidth - e.clientWidth) : 0
		return { page: wider(document.scrollingElement), view: wider(document.querySelector(".router-view")) }
	})
}

async function expectNoSidewaysScroll(page: Page, where: string) {
	// a layout settles after the data arrives: wait for the network to be quiet before measuring
	await page.waitForLoadState("networkidle")
	expect(await overflow(page), where).toEqual({ page: 0, view: 0 })
}

test.beforeEach(async ({ page }) => stubMapTiles(page))

for (const view of ["playlist", "schedule", "system"]) {
	test(`the ${view} page does not scroll sideways`, async ({ page }) => {
		const watch = watchProblems(page)
		await page.goto(`/#/${view}`)
		await expectNoSidewaysScroll(page, view)
		watch.expectNone()
	})
}

test("no settings tab scrolls sideways", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	const tabs = page.getByRole("tab")
	await expect(tabs.first()).toBeVisible()
	const count = await tabs.count()
	expect(count).toBeGreaterThan(3)
	for (let i = 0; i < count; i++) {
		const tab = tabs.nth(i)
		const name = (await tab.textContent())?.trim() ?? `tab ${i}`
		await tab.click()
		await expect(page.getByRole("tabpanel")).toBeVisible()
		await expectNoSidewaysScroll(page, name)
	}
	watch.expectNone()
})
