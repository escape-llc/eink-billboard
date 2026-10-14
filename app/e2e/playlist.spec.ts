import fs from "node:fs"
import path from "node:path"
import { expect, test, type Page } from "@playwright/test"
import { OPEN } from "./servers"
import { stubMapTiles, watchProblems } from "./support"

// These tests change the schedules on the open server; the folder is put back afterwards so the other specs see the fixture.
test.describe.configure({ mode: "serial" })
const FOLDER = path.join(OPEN.storage, "schedules")
const FILE = path.join(FOLDER, "playlist.json")
const API = "/api/schedule/playlist"
const snapshot = new Map<string, string>()
const stored = () => JSON.parse(fs.readFileSync(FILE, "utf8"))

test.beforeAll(() => { for (const name of fs.readdirSync(FOLDER)) snapshot.set(name, fs.readFileSync(path.join(FOLDER, name), "utf8")) })
const restore = () => {
	for (const name of fs.readdirSync(FOLDER)) if (!snapshot.has(name)) fs.rmSync(path.join(FOLDER, name))
	for (const [name, text] of snapshot) fs.writeFileSync(path.join(FOLDER, name), text)
}
test.afterAll(restore)
test.beforeEach(async ({ page }) => {
	restore()
	await stubMapTiles(page)
})

const row = (page: Page, title: string) => page.locator(".track-row").filter({ hasText: title })
const save = (page: Page) => page.getByRole("button", { name: "Save playlist" })
const apply = (page: Page) => page.getByRole("button", { name: "Apply track" })

test("a track edit is applied to the working copy and saved with the whole playlist", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/playlist")
	await row(page, "Morning slides").click()
	const title = page.locator(".track-editor input[type=text]").first()
	await expect(title).toHaveValue("Morning slides")
	await title.fill("Morning, renamed")
	await expect(save(page)).toBeDisabled()
	await apply(page).click()
	await expect(page.getByText(/Unsaved changes/)).toBeVisible()
	// nothing is stored until the playlist is saved
	expect(stored().items[0].title).toBe("Morning slides")
	await save(page).click()
	await expect(page.getByText("Playlist saved")).toBeVisible()
	await expect(page.getByText(/Unsaved changes/)).toBeHidden()
	const items = stored().items
	expect(items.map((x: { title: string }) => x.title)).toEqual(["Morning, renamed", "Evening slides"])
	expect(items[0].type).toBe("PlaylistSchedule")
	expect(items[0].content.slideMax).toBe(4)
	expect(items[1].content.slideMax).toBe(2)
	watch.expectNone()
})

test("tracks can be added, moved and removed, and the order is saved", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/playlist")
	await page.getByRole("button", { name: "Add track" }).click()
	const title = page.locator(".track-editor input[type=text]").first()
	await title.fill("Third")
	await page.locator(".track-editor .p-select").filter({ hasText: "Data Source" }).first().click()
	await page.getByRole("option").filter({ hasText: "Year Progress" }).first().click()
	await apply(page).click()
	await row(page, "Third").getByRole("button", { name: "Move up" }).click()
	await row(page, "Evening slides").getByRole("button", { name: "Remove track" }).click()
	await save(page).click()
	await expect(page.getByText("Playlist saved")).toBeVisible()
	const items = stored().items
	expect(items.map((x: { title: string }) => x.title)).toEqual(["Morning slides", "Third"])
	expect(items[1].content.dataSource).toBe("year_progress")
	expect(items[1].id).not.toMatch(/^new-/)
	watch.expectNone()
})

test("a change made elsewhere is a conflict that can be reloaded or overwritten", async ({ page, request }) => {
	const watch = watchProblems(page, [409], [/409|Conflict/i])
	await page.goto("/#/playlist")
	await row(page, "Morning slides").click()
	const title = page.locator(".track-editor input[type=text]").first()
	await title.fill("Mine")
	await apply(page).click()
	const doc = (await (await request.get(`${OPEN.url}${API}/e2e-playlist`)).json()).schedule
	expect((await request.patch(`${OPEN.url}${API}/e2e-playlist`, { data: { name: "Renamed elsewhere", _rev: doc._rev } })).ok()).toBeTruthy()
	await save(page).click()
	await expect(page.getByText(/changed|mismatch/i).first()).toBeVisible()
	expect(stored().name).toBe("Renamed elsewhere")
	await page.getByRole("button", { name: "Overwrite" }).click()
	await expect(page.getByText("Playlist saved")).toBeVisible()
	expect(stored().items[0].title).toBe("Mine")
	watch.expectNone()
})

test("there can be many playlists: create, switch, rename, delete", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/playlist")
	await page.getByRole("button", { name: "New playlist" }).click()
	await page.getByLabel("Playlist name").fill("Second playlist")
	await page.getByRole("button", { name: "OK" }).click()
	await expect(page.getByRole("combobox", { name: "Playlist" })).toContainText("Second playlist")
	await expect.poll(() => fs.readdirSync(FOLDER).length).toBe(snapshot.size + 1)
	await expect(page.locator(".track-row")).toHaveCount(0)

	await page.getByRole("button", { name: "Rename playlist" }).click()
	await page.getByLabel("Playlist name").fill("Renamed playlist")
	await page.getByRole("button", { name: "OK" }).click()
	await expect(page.getByRole("combobox", { name: "Playlist" })).toContainText("Renamed playlist")

	await page.getByRole("combobox", { name: "Playlist" }).click()
	await page.getByRole("option", { name: "E2E Playlist" }).click()
	await expect(row(page, "Morning slides")).toBeVisible()

	await page.getByRole("combobox", { name: "Playlist" }).click()
	await page.getByRole("option", { name: "Renamed playlist" }).click()
	await page.getByRole("button", { name: "Delete playlist" }).click()
	await page.getByRole("dialog", { name: "Delete playlist?" }).getByRole("button", { name: "Delete" }).click()
	await expect(page.getByText("Playlist deleted")).toBeVisible()
	await expect.poll(() => fs.readdirSync(FOLDER).length).toBe(snapshot.size)
	await expect(row(page, "Morning slides")).toBeVisible()
	watch.expectNone()
})

test("leaving a playlist with unsaved changes asks first", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/playlist")
	await page.getByRole("button", { name: "New playlist" }).click()
	await page.getByLabel("Playlist name").fill("Other")
	await page.getByRole("button", { name: "OK" }).click()
	await expect(page.getByRole("combobox", { name: "Playlist" })).toContainText("Other")
	await page.getByRole("button", { name: "Add track" }).click()
	await expect(page.getByText(/Unsaved changes/)).toBeVisible()
	await page.getByRole("combobox", { name: "Playlist" }).click()
	await page.getByRole("option", { name: "E2E Playlist" }).click()
	const ask = page.getByRole("dialog", { name: "Discard unsaved changes?" })
	await expect(ask).toBeVisible()
	await ask.getByRole("button", { name: "Keep editing" }).click()
	await expect(page.getByRole("combobox", { name: "Playlist" })).toContainText("Other")
	await page.getByRole("combobox", { name: "Playlist" }).click()
	await page.getByRole("option", { name: "E2E Playlist" }).click()
	await page.getByRole("dialog", { name: "Discard unsaved changes?" }).getByRole("button", { name: "Discard" }).click()
	await expect(row(page, "Morning slides")).toBeVisible()
	watch.expectNone()
})

// the panels are surfaces of the theme (PrimeVue tokens): in dark mode they are dark, with text that can be read on them
function luminance(rgb: string): number {
	const [r, g, b] = (rgb.match(/[\d.]+/g) ?? ["0", "0", "0"]).slice(0, 3).map(Number).map(v => v / 255)
	return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

test("the track list and the editor follow the theme: dark in dark mode, light in light mode", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/playlist")
	await row(page, "Morning slides").waitFor()
	const surfaces = () => page.evaluate(() => ["track-list", "track-editor"].map(c => {
		const el = document.querySelector(`.${c}`) as HTMLElement
		return { bg: getComputedStyle(el).backgroundColor, text: getComputedStyle(el.querySelector(".title, label, input") ?? el).color }
	}))
	await page.evaluate(() => document.documentElement.classList.remove("app-dark-mode"))
	for (const s of await surfaces()) expect(luminance(s.bg), `light mode ${s.bg}`).toBeGreaterThan(0.6)
	await page.evaluate(() => document.documentElement.classList.add("app-dark-mode"))
	for (const s of await surfaces()) {
		expect(luminance(s.bg), `dark mode ${s.bg}`).toBeLessThan(0.25)
		expect(luminance(s.text) - luminance(s.bg), "text is lighter than its surface").toBeGreaterThan(0.3)
	}
	watch.expectNone()
})

test("the help under the track's fields can be hidden from the header, and the playlist's actions are one group", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/playlist")
	// the selector and every action sit in one group
	const actions = page.locator(".playlist-actions")
	await expect(actions.getByRole("combobox", { name: "Playlist" })).toBeVisible()
	for (const name of ["New playlist", "Rename playlist", "Delete playlist", "Add track", "Save playlist"]) await expect(actions.getByRole("button", { name })).toBeVisible()
	await row(page, "Morning slides").click()
	const help = page.locator(".track-editor .field-help")
	const toggle = page.getByRole("button", { name: "Help text" })
	await expect(help.first()).toBeVisible()
	await expect(toggle).toHaveAttribute("aria-pressed", "true")
	await toggle.click()
	await expect(help).toHaveCount(0)
	await expect(toggle).toHaveAttribute("aria-pressed", "false")
	// the fields are still there, and hiding the help changes nothing to apply
	await expect(page.locator(".track-editor input[type=text]").first()).toHaveValue("Morning slides")
	await expect(save(page)).toBeDisabled()
	await toggle.click()
	await expect(help.first()).toBeVisible()
	watch.expectNone()
})

// A stored track is compared with the plugin's and the data source's current properties: a property it lacks is tagged new (and takes its default), one the schema
// no longer defines is listed dimmed, by name, and left out when the track is saved. A weather track before the calendar one used to leave a stale "Required" on Agenda Days.
test("a stored track shows what is new and what is no longer used, and a field the schema fills is not an error", async ({ page }) => {
	const watch = watchProblems(page)
	const track = (id: string, title: string, content: object) => ({ type: "PlaylistSchedule", plugin_name: "slide-show", id, title, content })
	const doc = JSON.parse(fs.readFileSync(FILE, "utf8"))
	doc.items = [
		track("w", "0 Item", { dataSource: "weather", views: ["current"], title: null, fontSize: "normal", slideMax: 0, slideMinutes: 2, showAs: "auto" }),
		// no `fontSize`, no `listMode`: new; `washStyle` and `oldSetting`: deleted
		track("c", "1 Item", { dataSource: "calendar", views: ["agenda"], calendars: [], holidaySets: [], agendaDays: 7, title: "Agenda", slideMax: 0, slideMinutes: 2, showAs: "auto", weeksAhead: null, washStyle: "soft", oldSetting: 3 }),
	]
	fs.writeFileSync(FILE, JSON.stringify(doc, null, 2))
	await page.goto("/#/playlist")
	await row(page, "0 Item").click()
	await expect(page.locator(".track-editor #views")).toBeVisible()
	await row(page, "1 Item").click()
	const editor = page.locator(".track-editor")
	await expect(editor.locator("#agendaDays")).toHaveValue("7")
	// no error on a field that has its value
	await expect(editor.locator(".p-message-error")).toHaveCount(0)
	// new: the fields the track lacks, tagged, at their defaults
	await expect(editor.locator("label[for=fontSize] .new-tag")).toHaveText("new")
	await expect(editor.locator("label[for=listMode] .new-tag")).toHaveText("new")
	await expect(editor.locator("label[for=agendaDays] .new-tag")).toHaveCount(0)
	// deleted: names only, never values
	const stale = editor.getByTestId("stale-field")
	await expect(stale).toHaveText([/washStyle/, /oldSetting/])
	await expect(editor.getByTestId("stale-fields")).not.toContainText("soft")
	// applying the track leaves them out
	await apply(page).click()
	await save(page).click()
	await expect(page.getByText("Playlist saved")).toBeVisible()
	const content = stored().items.find((x: { id: string }) => x.id === "c").content
	expect(Object.keys(content)).not.toContain("washStyle")
	expect(Object.keys(content)).not.toContain("oldSetting")
	expect(content.fontSize).toBe("normal")
	expect(content.agendaDays).toBe(7)
	// a track that was just added has nothing to compare with
	await page.getByRole("button", { name: "Add track" }).click()
	await expect(page.locator(".track-editor .new-tag")).toHaveCount(0)
	await expect(page.getByTestId("stale-fields")).toHaveCount(0)
	watch.expectNone()
})
