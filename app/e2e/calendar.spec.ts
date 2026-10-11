import fs from "node:fs"
import path from "node:path"
import { expect, test, type Page } from "@playwright/test"
import { OPEN } from "./servers"
import { saveButton, stubMapTiles, watchProblems } from "./support"

// The Calendar data source keeps its calendars and holiday sets in its settings (rows with secrets and fields shown per choice), and a track
// chooses some of them by name (a multi-select). These tests edit the settings on the open server, so the file is put back afterwards.
test.describe.configure({ mode: "serial" })
const FILE = path.join(OPEN.storage, "datasources", "calendar", "settings.json")
let original = ""
test.beforeAll(() => { original = fs.readFileSync(FILE, "utf8") })
test.afterAll(() => { fs.writeFileSync(FILE, original) })
test.beforeEach(async ({ page }) => stubMapTiles(page))
// put the settings back through the API, not the file: the server keeps the document it last read until its watcher sees the change
test.afterEach(async ({ request }) => {
	const current = await (await request.get("/api/datasources/calendar/settings")).json()
	const resp = await request.put("/api/datasources/calendar/settings", { data: { ...JSON.parse(original), _rev: current._rev } })
	expect(resp.ok()).toBeTruthy()
})

async function openCalendarSettings(page: Page) {
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Data Sources" }).click()
	await page.getByRole("tabpanel").locator(".p-select").first().click()
	await page.getByRole("option", { name: /^calendar/ }).click()
	await expect(page.getByRole("textbox", { name: "Name 1", exact: true }).first()).toHaveValue("Family")
}
const calendars = (page: Page) => page.getByRole("group", { name: "Calendars" })

test("a calendar row shows the sign-in fields its choice needs, and its password is kept but never sent back", async ({ page, request }) => {
	const watch = watchProblems(page)
	await openCalendarSettings(page)
	const rows = calendars(page)
	await expect(rows.getByRole("textbox", { name: "Password 1", exact: true })).toHaveCount(0)
	// each row is a block of labelled fields (more than four), with a color picker
	await expect(rows.getByText("Address").first()).toBeVisible()
	await expect(rows.getByRole("textbox", { name: "Color 1", exact: true })).toHaveValue("#3366cc")

	await rows.getByRole("combobox", { name: "Sign-in 1" }).click()
	await page.getByRole("option", { name: "bearer", exact: true }).click()
	await expect(rows.getByRole("textbox", { name: "Token 1", exact: true })).toBeVisible()
	await expect(rows.getByRole("textbox", { name: "Password 1", exact: true })).toHaveCount(0)
	await rows.getByRole("combobox", { name: "Sign-in 1" }).click()
	await page.getByRole("option", { name: "basic", exact: true }).click()
	await expect(rows.getByRole("textbox", { name: "Token 1", exact: true })).toHaveCount(0)
	await rows.getByRole("textbox", { name: "Username 1", exact: true }).fill("user")
	const password = rows.getByRole("textbox", { name: "Password 1", exact: true })
	await expect(password).toHaveAttribute("type", "password")
	await password.fill("hunter2")
	await saveButton(page).click()
	await expect(page.getByText("Settings saved successfully")).toBeVisible()

	const stored = JSON.parse(fs.readFileSync(FILE, "utf8"))
	expect(stored.calendars[0]).toMatchObject({ auth: "basic", username: "user", password: "hunter2", token: null })
	const sent = await (await request.get("/api/datasources/calendar/settings")).json()
	expect(sent.calendars[0].password).toBe("********")
	expect(JSON.stringify(sent)).not.toContain("hunter2")
	// the form shows the mask; saving it unchanged keeps the password
	await expect(password).toHaveValue("********")
	await rows.getByRole("textbox", { name: "Name 2", exact: true }).fill("Office")
	await saveButton(page).click()
	await expect(page.getByText("Settings saved successfully")).toBeVisible()
	expect(JSON.parse(fs.readFileSync(FILE, "utf8")).calendars[0].password).toBe("hunter2")
	watch.expectNone()
})

test("a holiday row chooses its country from the list the server sends", async ({ page }) => {
	const watch = watchProblems(page)
	await openCalendarSettings(page)
	const holidays = page.getByRole("group", { name: "Holidays" })
	await expect(holidays.getByRole("combobox", { name: "Country 1" })).toContainText("United States")
	await holidays.getByRole("combobox", { name: "Country 1" }).click()
	await expect(page.getByRole("option", { name: "Canada", exact: true })).toBeVisible()
	await page.getByRole("option", { name: "Canada", exact: true }).click()
	await saveButton(page).click()
	await expect(page.getByText("Settings saved successfully")).toBeVisible()
	expect(JSON.parse(fs.readFileSync(FILE, "utf8")).holidays[0].country).toBe("CA")
	watch.expectNone()
})

test("a calendar address is tested through the real route, which refuses this device", async ({ page }) => {
	const watch = watchProblems(page)
	await openCalendarSettings(page)
	const rows = calendars(page)
	await rows.getByRole("textbox", { name: "Address 1", exact: true }).fill("webcal://127.0.0.1:1/x.ics")
	await rows.getByRole("button", { name: "Test Address 1" }).click()
	await expect(page.getByText("cannot be tested here")).toBeVisible()
	watch.expectNone()
})

test("a track picks views and calendars from the settings, and the agenda's days show only with the agenda", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/playlist")
	await page.getByRole("button", { name: "Add track" }).click()
	await page.locator(".track-editor input[type=text]").first().fill("Calendar")
	await page.locator(".track-editor .p-select").filter({ hasText: "Data Source" }).first().click()
	await page.getByRole("option").filter({ hasText: "Calendar" }).first().click()
	const editor = page.locator(".track-editor")
	await expect(editor.getByText("Agenda Days")).toHaveCount(0)
	await editor.locator(".p-multiselect").filter({ hasText: "month" }).click()
	await page.getByRole("option", { name: "agenda" }).click()
	await page.keyboard.press("Escape")
	await expect(editor.getByText("Agenda Days")).toBeVisible()

	await editor.locator(".p-multiselect").filter({ hasText: "Calendars" }).click()
	await expect(page.getByRole("option")).toHaveText(["Family", "Work"])
	await page.getByRole("option", { name: "Work" }).click()
	await page.keyboard.press("Escape")
	await page.getByRole("button", { name: "Apply track" }).click()
	await page.getByRole("button", { name: "Save playlist" }).click()
	await expect(page.getByText("Playlist saved")).toBeVisible()
	const items = JSON.parse(fs.readFileSync(path.join(OPEN.storage, "schedules", "playlist.json"), "utf8")).items
	const track = items.find((x: { title: string }) => x.title === "Calendar")
	expect(track.content).toMatchObject({ dataSource: "calendar", views: ["month", "agenda"], calendars: ["Work"], agendaDays: 7 })
	fs.writeFileSync(path.join(OPEN.storage, "schedules", "playlist.json"), JSON.stringify({ ...JSON.parse(fs.readFileSync(path.join(OPEN.storage, "schedules", "playlist.json"), "utf8")), items: items.filter((x: { title: string }) => x.title !== "Calendar") }, null, "\t"))
	watch.expectNone()
})
