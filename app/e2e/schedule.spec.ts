import fs from "node:fs"
import path from "node:path"
import { expect, test, type Page } from "@playwright/test"
import { OPEN } from "./servers"
import { stubMapTiles, watchProblems } from "./support"

// These tests change the schedule on the open server; the file is put back afterwards so the other specs see the fixture.
test.describe.configure({ mode: "serial" })
const FILE = path.join(OPEN.storage, "schedules", "timer_tasks.json")
const DOC = "e2e-timer-tasks"
const TASKS = `/api/schedule/timer/${DOC}/items`
let original = ""
const stored = () => JSON.parse(fs.readFileSync(FILE, "utf8"))
const storedTask = (id: string) => stored().items.find((x: { id: string }) => x.id === id)

test.beforeAll(() => { original = fs.readFileSync(FILE, "utf8") })
test.afterAll(() => { fs.writeFileSync(FILE, original) })
test.beforeEach(async ({ page }) => {
	fs.writeFileSync(FILE, original)
	await stubMapTiles(page)
})

const dialog = (page: Page) => page.getByRole("dialog", { name: "Edit task" })
test("the scheduler fills the window and only its hours scroll", async ({ page }) => {
	await page.setViewportSize({ width: 1280, height: 700 })
	await page.goto("/#/schedule")
	await expect(page.locator(".event").first()).toBeVisible()
	const sizes = await page.evaluate(() => {
		const area = document.querySelector(".router-view") as HTMLElement
		const hours = document.querySelector(".events-panel-scroll") as HTMLElement
		return { areaScrolls: area.scrollHeight > area.clientHeight + 1, hoursScroll: hours.scrollHeight > hours.clientHeight + 1,
			pageScrolls: document.documentElement.scrollHeight > window.innerHeight + 1, bottom: hours.getBoundingClientRect().bottom, area: area.getBoundingClientRect().bottom }
	})
	expect(sizes.areaScrolls).toBe(false)
	expect(sizes.pageScrolls).toBe(false)
	expect(sizes.hoursScroll).toBe(true)
	// the hours reach the bottom of the page area
	expect(sizes.area - sizes.bottom).toBeLessThan(20)
})

test("the playlist editor fills the window: the page does not scroll, its panes do", async ({ page }) => {
	await page.setViewportSize({ width: 1280, height: 420 })
	await page.goto("/#/playlist")
	await page.locator(".track-row").first().click()
	await expect(page.getByText("Track Settings")).toBeVisible()
	await expect(page.getByText("Slide Duration Minutes")).toBeVisible()
	const sizes = await page.evaluate(() => {
		const area = document.querySelector(".router-view") as HTMLElement
		const editor = document.querySelector(".track-editor") as HTMLElement
		return { areaScrolls: area.scrollHeight > area.clientHeight + 1, pageScrolls: document.documentElement.scrollHeight > window.innerHeight + 1,
			editorScrolls: editor.scrollHeight > editor.clientHeight + 1, editorBottom: editor.getBoundingClientRect().bottom, areaBottom: area.getBoundingClientRect().bottom }
	})
	expect(sizes.areaScrolls).toBe(false)
	expect(sizes.pageScrolls).toBe(false)
	expect(sizes.editorScrolls).toBe(true)
	expect(sizes.areaBottom - sizes.editorBottom).toBeLessThan(20)
})

async function openFirstQuarterHourTask(page: Page) {
	await page.goto("/#/schedule")
	await page.locator(".event").filter({ hasText: "Quarter-hour clock" }).first().click()
	await expect(dialog(page)).toBeVisible()
	const title = dialog(page).locator("input[name=title]")
	await expect(title).toHaveValue("Quarter-hour clock")
	return title
}

test("editing a task saves just that task, and the timeline shows the change", async ({ page }) => {
	const watch = watchProblems(page)
	const title = await openFirstQuarterHourTask(page)
	await title.fill("Renamed quarter-hour clock")
	await dialog(page).getByRole("button", { name: "Save", exact: true }).last().click()
	await expect(page.getByText("Task saved")).toBeVisible()
	await expect(dialog(page)).toBeHidden()
	await expect.poll(() => storedTask("task1").title).toBe("Renamed quarter-hour clock")
	// nothing else changed
	expect(storedTask("task2").title).toBe("Paused year progress")
	expect(storedTask("task1").task.content.clockFace).toBe("Gradient Clock")
	await expect(page.locator(".event").filter({ hasText: "Renamed quarter-hour clock" }).first()).toBeVisible()
	watch.expectNone()
})

test("a change made elsewhere is a conflict that can be reloaded or overwritten", async ({ page, request }) => {
	const watch = watchProblems(page, [409], [/409|Conflict/i])
	const title = await openFirstQuarterHourTask(page)
	// somebody else renames the same task after this page loaded it
	const current = (await (await request.get(`${OPEN.url}${TASKS}/task1`)).json()).task
	const other = await request.patch(`${OPEN.url}${TASKS}/task1`, { data: { title: "Changed elsewhere", _rev: current._rev } })
	expect(other.ok()).toBeTruthy()

	await title.fill("My version")
	await dialog(page).getByRole("button", { name: "Save", exact: true }).last().click()
	await expect(dialog(page).getByText(/changed|mismatch/i).first()).toBeVisible()
	expect(storedTask("task1").title).toBe("Changed elsewhere")

	// Reload takes their version and drops my edit
	await dialog(page).getByRole("button", { name: "Reload" }).click()
	await expect(title).toHaveValue("Changed elsewhere")

	// edit again, conflict again, and this time overwrite
	await request.patch(`${OPEN.url}${TASKS}/task1`, { data: { title: "Changed again", _rev: (await (await request.get(`${OPEN.url}${TASKS}/task1`)).json()).task._rev } })
	await title.fill("Mine wins")
	await dialog(page).getByRole("button", { name: "Save", exact: true }).last().click()
	await dialog(page).getByRole("button", { name: "Overwrite" }).click()
	await expect(page.getByText("Task saved")).toBeVisible()
	await expect.poll(() => storedTask("task1").title).toBe("Mine wins")
	watch.expectNone()
})

test("a task can be added", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/schedule")
	await page.getByRole("button", { name: "New task" }).click()
	const created = page.getByRole("dialog", { name: "New task" })
	await expect(created).toBeVisible()
	await created.locator("input[name=title]").fill("Added in the browser")
	// the plugin is picked by name (the list is in the folders' order): Priority Update has a required data source
	await created.locator(".p-select").filter({ hasText: "Overlay" }).first().click()
	await page.getByRole("option").filter({ hasText: "Priority Update" }).first().click()
	// the plugin's own fields: a data source is required
	await created.locator(".p-select").filter({ hasText: "Data Source" }).first().click()
	await page.getByRole("option").filter({ hasText: "Year Progress" }).first().click()
	await created.getByRole("button", { name: "Save", exact: true }).last().click()
	await expect(page.getByText("Task saved")).toBeVisible()
	await expect.poll(() => stored().items.length).toBe(3)
	const added = stored().items.find((x: { title: string }) => x.title === "Added in the browser")
	expect(added.task.content.dataSource).toBe("year_progress")
	expect(added.trigger.time).toEqual({ type: "specific", hour: 9, minute: 0 })
	watch.expectNone()
})

test("a new task is offered the timer plugins only, and the form follows the plugin", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/schedule")
	await page.getByRole("button", { name: "New task" }).click()
	const created = page.getByRole("dialog", { name: "New task" })
	await expect(created).toBeVisible()
	// the plugin list: the timer plugins (priority, overlay), not the playlist's Slide Show
	await created.locator(".p-select").filter({ hasText: "Overlay" }).first().click()
	await expect(page.getByRole("option")).toHaveCount(2)
	await expect(page.getByRole("option").filter({ hasText: "Slide Show" })).toHaveCount(0)
	// the plugin is the form's own field list: each brings its own fields
	await expect(created.locator("label", { hasText: "Zone" })).toBeVisible()
	await page.getByRole("option").filter({ hasText: "Priority Update" }).first().click()
	await expect(created.locator("label", { hasText: "Slide Duration" })).toBeVisible()
	await expect(created.locator("label", { hasText: "Zone" })).toHaveCount(0)
	// and starts at that plugin's defaults, not blank
	await expect(created.locator("input[name=slideMinutes]")).toHaveValue("1")
	watch.expectNone()
})
test("a task can be deleted after a confirmation", async ({ page }) => {
	const watch = watchProblems(page)
	await openFirstQuarterHourTask(page)
	await dialog(page).getByRole("button", { name: "Delete" }).click()
	const confirm = page.getByRole("dialog", { name: "Delete task?" })
	await expect(confirm).toBeVisible()
	await confirm.getByRole("button", { name: "Keep" }).click()
	expect(storedTask("task1")).toBeDefined()
	await dialog(page).getByRole("button", { name: "Delete" }).click()
	await page.getByRole("dialog", { name: "Delete task?" }).getByRole("button", { name: "Delete" }).click()
	await expect(page.getByText("Task deleted")).toBeVisible()
	await expect.poll(() => storedTask("task1")).toBeUndefined()
	expect(storedTask("task2")).toBeDefined()
	watch.expectNone()
})

test("a server problem with a field shows on the form", async ({ page }) => {
	const watch = watchProblems(page, [422], [/422/])
	const title = await openFirstQuarterHourTask(page)
	// the descriptor allows one more minute than the server would: break a stored value server-side only
	await page.route("**/api/schedule/timer/**/items/task1", async route => {
		if (route.request().method() === "PUT") {
			await route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ success: false, message: "Schedule validation failed", id: DOC,
				errors: [{ path: ["task", "content", "slideMinutes"], message: "Minimum 1" }] }) })
		}
		else await route.continue()
	})
	await title.fill("Will be refused")
	await dialog(page).getByRole("button", { name: "Save", exact: true }).last().click()
	await expect(dialog(page).getByText("Minimum 1")).toBeVisible()
	expect(storedTask("task1").title).toBe("Quarter-hour clock")
	watch.expectNone()
})

test("a color field is picked or typed, and a value that is not a color is refused on the field", async ({ page }) => {
	const watch = watchProblems(page)
	await openFirstQuarterHourTask(page)
	const color = dialog(page).getByRole("textbox", { name: "Primary Color", exact: true })
	await expect(color).toHaveValue("#db3246")
	await expect(dialog(page).getByLabel("Primary Color picker")).toBeVisible()
	await color.fill("blue")
	await expect(dialog(page).getByText("Enter a color like #3366cc")).toBeVisible()
	await color.fill("#123abc")
	await expect(dialog(page).getByText("Enter a color like #3366cc")).toBeHidden()
	await dialog(page).getByRole("button", { name: "Save", exact: true }).last().click()
	await expect(page.getByText("Task saved")).toBeVisible()
	await expect.poll(() => storedTask("task1").task.content.primaryColor).toBe("#123abc")
	watch.expectNone()
})

test("the toolbar shows a day or a week from today, moves forward and back but never before today", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/schedule")
	await expect(page.locator(".event").first()).toBeVisible()
	const range = page.getByTestId("range")
	const back = page.getByRole("button", { name: "Back" })
	const forward = page.getByRole("button", { name: "Forward" })
	const headers = page.locator(".day-header")
	// the view, the moves and a new task are one group
	const actions = page.locator(".scheduler-actions")
	for (const name of ["Day", "Week", "List", "Back", "Today", "Forward", "New task"]) await expect(actions.getByRole("button", { name, exact: true })).toBeVisible()
	await expect(actions.getByRole("button", { name: "Week", exact: true })).toHaveAttribute("aria-pressed", "true")
	// a week from today, starting on today's weekday
	await expect(headers).toHaveCount(7)
	await expect(headers.first()).toHaveClass(/day-header-today/)
	const thisWeek = await range.textContent()
	await expect(back).toBeDisabled()
	await expect(page.getByRole("button", { name: "Today" })).toBeDisabled()
	await forward.click()
	await expect(range).not.toHaveText(thisWeek ?? "")
	await expect(headers.first()).not.toHaveClass(/day-header-today/)
	// the same weekday a week on: the header's weekday is today's
	const weekday = async () => (await headers.first().locator(".day-header-dow").textContent())?.trim()
	const nextWeekday = await weekday()
	await back.click()
	await expect(range).toHaveText(thisWeek ?? "")
	expect(await weekday()).toBe(nextWeekday)
	await expect(back).toBeDisabled()
	// a day
	await page.getByRole("button", { name: "Day", exact: true }).click()
	await expect(page.getByRole("button", { name: "Day", exact: true })).toHaveAttribute("aria-pressed", "true")
	await expect(headers).toHaveCount(1)
	await forward.click()
	await expect(back).toBeEnabled()
	await page.getByRole("button", { name: "Today" }).click()
	await expect(back).toBeDisabled()
	await expect(headers.first()).toHaveClass(/day-header-today/)
	watch.expectNone()
})

test("the list shows each task once and opens it", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/schedule")
	await expect(page.locator(".event").first()).toBeVisible()
	const repeats = await page.locator(".event").filter({ hasText: "Quarter-hour clock" }).count()
	expect(repeats).toBeGreaterThan(1)
	await page.getByRole("button", { name: "List", exact: true }).click()
	const list = page.getByTestId("task-list")
	await expect(list.getByRole("button", { name: /^Edit / })).toHaveCount(stored().items.length)
	const row = list.getByRole("row").filter({ hasText: "Quarter-hour clock" })
	await expect(row).toHaveCount(1)
	await expect(row.locator(".runs")).toHaveText(/^\d+$/)
	await list.getByRole("button", { name: "Edit Quarter-hour clock" }).click()
	await expect(dialog(page)).toBeVisible()
	await expect(dialog(page).locator("input[name=title]")).toHaveValue("Quarter-hour clock")
	watch.expectNone()
})
