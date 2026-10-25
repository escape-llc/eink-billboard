import fs from "node:fs"
import path from "node:path"
import { expect, test, type Page } from "@playwright/test"
import { OPEN } from "./servers"
import { stubMapTiles, watchProblems } from "./support"

// A change made elsewhere reaches an open page (#549): the server's file watcher names the routes it changed on the telemetry link, and the page's cache of
// the API's answers fetches what it shows again. The test changes the Image Folder's settings file itself, as a hand edit or the device's command line
// would (no request of this page, nor any API call, is involved), and puts it back afterwards for the other specs.
test.describe.configure({ mode: "serial" })
const FILE = path.join(OPEN.storage, "datasources", "image-folder", "settings.json")
let original = ""
test.beforeAll(() => { original = fs.readFileSync(FILE, "utf8") })
// put back, and wait until the server reads it again (it serves what it read until the watcher tells it the file changed): the next spec loads these settings
test.afterAll(async ({ request }) => {
	fs.writeFileSync(FILE, original)
	const count = JSON.parse(original).folders.length
	await expect.poll(async () => (await (await request.get("/api/datasources/image-folder/settings")).json()).folders.length, { timeout: 15_000 }).toBe(count)
})
test.beforeEach(async ({ page }) => stubMapTiles(page))

/** The folder choices the open track offers. */
async function folderChoices(page: Page) {
	await page.locator(".track-editor .p-select").filter({ hasText: "E2E images" }).click()
	const options = page.getByRole("option")
	return { options, close: () => page.keyboard.press("Escape") }
}

test("a list changed in a stored file reaches an open form's choices without a reload", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/playlist")
	await page.locator(".track-row").filter({ hasText: "Morning slides" }).click()
	let choices = await folderChoices(page)
	await expect(choices.options).toHaveText(["E2E images"])
	await choices.close()
	// a reload would forget this
	await page.evaluate(() => { (window as unknown as { stayed: boolean }).stayed = true })

	const doc = JSON.parse(original)
	fs.writeFileSync(FILE, JSON.stringify({ ...doc, folders: [...doc.folders, { name: "Added elsewhere", path: doc.folders[0].path }] }, null, "\t"))

	// the watcher's event reaches the page and the choices are asked for again: open the list until it shows them
	await expect(async () => {
		choices = await folderChoices(page)
		try { await expect(choices.options).toHaveText(["E2E images", "Added elsewhere"], { timeout: 1000 }) }
		finally { await choices.close() }
	}).toPass({ timeout: 15_000 })
	expect(await page.evaluate(() => (window as unknown as { stayed?: boolean }).stayed)).toBe(true)
	watch.expectNone()
})
