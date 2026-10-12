import fs from "node:fs"
import path from "node:path"
import { expect, test } from "@playwright/test"
import { OPEN } from "./servers"
import { saveButton, stubMapTiles, watchProblems } from "./support"

// The Image Folder data source keeps its folders in its settings and a track names one: the choices a track offers are whatever
// the settings list says. The test edits that file on the open server, so it is put back afterwards for the other specs.
test.describe.configure({ mode: "serial" })
const FILE = path.join(OPEN.storage, "datasources", "image-folder", "settings.json")
let original = ""
test.beforeAll(() => { original = fs.readFileSync(FILE, "utf8") })
test.afterAll(() => { fs.writeFileSync(FILE, original) })
test.beforeEach(async ({ page }) => stubMapTiles(page))

test("folders are added in the data source's settings, and a track chooses among them by name", async ({ page, request }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Data Sources" }).click()
	await page.getByRole("tabpanel").locator(".p-select").first().click()
	await page.getByRole("option").filter({ hasText: "image-folder" }).click()
	await expect(page.getByRole("textbox", { name: "Name 1", exact: true })).toHaveValue("E2E images")

	await page.getByRole("button", { name: "Add to Folders" }).click()
	await page.getByRole("textbox", { name: "Name 2", exact: true }).fill("Holiday")
	await page.getByRole("textbox", { name: "Folder Path 2", exact: true }).fill("/photos/holiday")
	await saveButton(page).click()
	await expect(page.getByText("Settings saved successfully")).toBeVisible()
	const settings = async () => (await (await request.get("/api/datasources/image-folder/settings")).json())
	expect((await settings()).folders.map((f: { name: string }) => f.name)).toEqual(["E2E images", "Holiday"])
	// what the track form will offer
	expect(await (await request.get("/api/datasources/image-folder/lookups/folder")).json())
		.toEqual([{ name: "E2E images", value: "E2E images" }, { name: "Holiday", value: "Holiday" }])

	// the settings were just saved, so leaving the page does not ask whether to discard them
	await page.goto("/#/playlist")
	await page.locator(".track-row").filter({ hasText: "Morning slides" }).click()
	// the track keeps the folder it names, and the other is on offer
	const folder = page.locator(".track-editor .p-select").filter({ hasText: "E2E images" })
	await expect(folder).toBeVisible()
	await folder.click()
	await expect(page.getByRole("option")).toHaveText(["E2E images", "Holiday"])
	watch.expectNone()
})

test("the RSS Feed settings test an address through the real route, which refuses this device", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Data Sources" }).click()
	await page.getByRole("tabpanel").locator(".p-select").first().click()
	await page.getByRole("option", { name: /^rss/ }).click()
	await page.getByRole("button", { name: "Add to Feeds" }).click()
	await page.getByRole("textbox", { name: "Name 1", exact: true }).fill("Loopback")
	const url = page.getByRole("textbox", { name: "Feed URL 1", exact: true })
	await url.fill("not an address")
	await expect(page.getByText("Enter a valid URL")).toBeVisible()
	await expect(page.getByRole("button", { name: "Test Feed URL 1" })).toBeDisabled()
	// no network is needed: a refused address is answered before anything is fetched
	await url.fill("http://127.0.0.1:1/feed.xml")
	await page.getByRole("button", { name: "Test Feed URL 1" }).click()
	await expect(page.getByText("cannot be used here")).toBeVisible()
	// the answer does not repeat the address (what is typed in the box is a value, not page text)
	await expect(page.getByText("127.0.0.1")).toHaveCount(0)
	watch.expectNone()
})

