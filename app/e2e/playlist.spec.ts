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
