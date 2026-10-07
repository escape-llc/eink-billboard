import { expect, test, type Page } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// The timeline draws what the server rendered, in the zone the server names, whatever the browser's zone is (it is New Zealand here).
test.use({ timezoneId: "Pacific/Auckland" })
test.beforeEach(async ({ page }) => stubMapTiles(page))

const TRIGGER = { on_startup: false, day: { type: "dayofweek", days: [0, 1, 2, 3, 4, 5, 6] }, time: { type: "specific", hour: 9, minute: 0 } }
const item = (id: string, title: string, minutes: number) => ({
	id, title, enabled: true, _rev: `rev-${id}`, trigger: TRIGGER, task: { plugin_name: "interstitial", content: { slideMinutes: minutes, dataSource: "year_progress" } }
})
async function stubRender(page: Page, render: object) {
	await page.route("**/api/schedule/tasks/render**", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(render) }))
}
const placement = (page: Page, title: string) => page.locator(".event").filter({ hasText: title }).evaluateAll(els => els.map(el => ({
	column: (el.parentElement as HTMLElement).style.gridColumn,
	row: (el as HTMLElement).style.gridRow
})))

test("a week across the end of daylight-saving time has seven days and keeps every event on its day, in the right slot", async ({ page }) => {
	const watch = watchProblems(page)
	await stubRender(page, {
		success: true, start_ts: "2026-10-30T00:00:00-04:00", end_ts: "2026-11-06T00:00:00-05:00", days: 7, timezone: "America/New_York",
		schedules: { s: { id: "s", name: "S", _rev: "r", items: [item("a", "On Nov 3", 15), item("b", "Late night", 90)] } },
		render: [
			{ schedule: "s", id: "a", scheduled_time: "2026-11-03T08:15:00-05:00" },
			{ schedule: "s", id: "b", scheduled_time: "2026-11-02T23:30:00-05:00" }
		],
		not_render: [], invalid: []
	})
	await page.goto("/#/schedule")
	// the days: the repeated hour of 1 Nov is not a repeated day
	await expect(page.locator(".day-header")).toHaveCount(7)
	expect((await page.locator(".day-header").allInnerTexts()).map(t => t.replace(/\s+/g, " ").trim()))
		.toEqual(["30Fri", "31Sat", "1Sun", "2Mon", "3Tue", "4Wed", "5Thu"])
	// 08:15 is in the 08:00 slot (row 17) of Nov 3 (column 6: the time column is 1)
	expect(await placement(page, "On Nov 3")).toEqual([{ column: "6", row: "17 / span 1" }])
	// 23:30 + 90 minutes: the last slot of Nov 2 (column 5), and the first two slots of Nov 3 as a continuation
	expect(await placement(page, "Late night")).toEqual([
		{ column: "5", row: "48 / span 1" },
		{ column: "6", row: "1 / span 2" }
	])
	watch.expectNone()
})

test("the time labels are whole hours and half hours of the device's day, in any zone", async ({ page }) => {
	const watch = watchProblems(page)
	await stubRender(page, {
		success: true, start_ts: "2026-01-05T00:00:00+05:30", end_ts: "2026-01-12T00:00:00+05:30", days: 7, timezone: "Asia/Kolkata",
		schedules: { s: { id: "s", name: "S", _rev: "r", items: [item("a", "Nine", 30)] } },
		render: [{ schedule: "s", id: "a", scheduled_time: "2026-01-05T09:00:00+05:30" }], not_render: [], invalid: []
	})
	await page.goto("/#/schedule")
	const labels = (await page.locator(".time-header").allInnerTexts()).map(t => t.replace(/\s+/g, " ").trim())
	expect(labels.slice(0, 4)).toEqual(["0000", "30", "0100", "30"])
	expect(labels).toHaveLength(48)
	expect(await placement(page, "Nine")).toEqual([{ column: "2", row: "19 / span 1" }])
	watch.expectNone()
})

test("an event can be opened from the keyboard", async ({ page }) => {
	const watch = watchProblems(page)
	await stubRender(page, {
		success: true, start_ts: "2026-01-05T00:00:00+00:00", end_ts: "2026-01-12T00:00:00+00:00", days: 7, timezone: "UTC",
		schedules: { s: { id: "s", name: "S", _rev: "r", items: [item("a", "Keyboard task", 30)] } },
		render: [{ schedule: "s", id: "a", scheduled_time: "2026-01-05T09:00:00+00:00" }], not_render: [], invalid: []
	})
	await page.goto("/#/schedule")
	const event = page.getByRole("button", { name: "Edit Keyboard task (interstitial)" })
	await expect(event).toBeVisible()
	await event.focus()
	await page.keyboard.press("Enter")
	await expect(page.getByRole("dialog", { name: "Edit task" })).toBeVisible()
	watch.expectNone()
})

test("today is highlighted in the server's zone", async ({ page }) => {
	const watch = watchProblems(page)
	// the real render: its first day is today in the device's zone
	await page.goto("/#/schedule")
	await expect(page.locator(".day-header-today")).toHaveCount(1)
	await expect(page.locator(".day-header").first()).toHaveClass(/day-header-today/)
	watch.expectNone()
})
