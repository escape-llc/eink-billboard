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
