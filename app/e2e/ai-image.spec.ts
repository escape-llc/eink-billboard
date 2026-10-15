import fs from "node:fs"
import path from "node:path"
import { expect, test, type Page } from "@playwright/test"
import { OPEN } from "./servers"
import { stubMapTiles, watchProblems } from "./support"

// A Generated Image chooses its parts (a text source, an image source), and each part's fields show under its choice, in the one track.
// The provider's lookups are answered here, in the browser: the test never reaches OpenAI.
test.describe.configure({ mode: "serial" })
const FOLDER = path.join(OPEN.storage, "schedules")
const FILE = path.join(FOLDER, "playlist.json")
const snapshot = new Map<string, string>()
test.beforeAll(() => { for (const name of fs.readdirSync(FOLDER)) snapshot.set(name, fs.readFileSync(path.join(FOLDER, name), "utf8")) })
const restore = () => {
	for (const name of fs.readdirSync(FOLDER)) if (!snapshot.has(name)) fs.rmSync(path.join(FOLDER, name))
	for (const [name, text] of snapshot) fs.writeFileSync(path.join(FOLDER, name), text)
}
test.afterAll(restore)

const choices = (...values: string[]) => values.map(value => ({ name: value, value }))
async function stubOpenAI(page: Page) {
	await page.route("**/api/datasource/openai/lookups/image-models", route => route.fulfill({ json: choices("gpt-image-2.5-flare", "gpt-image-2", "gpt-image-1.5") }))
	await page.route("**/api/datasource/openai/lookups/text-models", route => route.fulfill({ json: choices("gpt-5.6-sol", "gpt-5.6-luna") }))
	await page.route("**/api/datasource/openai/lookups/qualities", route => route.fulfill({ json: [{ name: "Auto (the model chooses)", value: "auto" }, { name: "High", value: "high" }] }))
}

test.beforeEach(async ({ page }) => {
	restore()
	await stubMapTiles(page)
	await stubOpenAI(page)
})

const editor = (page: Page) => page.locator(".track-editor")
const field = (page: Page, label: string) => editor(page).locator(".p-select").filter({ hasText: label }).first()

test("a Generated Image track shows each part's fields under its choice and saves them in one content", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/playlist")
	await page.getByRole("button", { name: "Add track" }).click()
	await editor(page).locator("input[type=text]").first().fill("Pictures")
	await field(page, "Data Source").click()
	await page.getByRole("option").filter({ hasText: "Generated Image" }).first().click()
	// the parts are chosen by default, and their own fields come with them
	await expect(editor(page).getByText("Image Source", { exact: true })).toBeVisible()
	await expect(editor(page).getByText("Text Source", { exact: true })).toBeVisible()
	await expect(editor(page).getByText("Image Model", { exact: true })).toBeVisible()
	await expect(editor(page).getByText("Text Model", { exact: true })).toBeVisible()
	await expect(editor(page).getByText("Moderation", { exact: true })).toBeVisible()
	// not rewriting hides the text source, and its part's fields with it
	await editor(page).locator(".p-toggleswitch").filter({ has: page.locator("#randomizePrompt") }).click()
	await expect(editor(page).getByText("Text Source", { exact: true })).toBeHidden()
	await expect(editor(page).getByText("Text Model", { exact: true })).toBeHidden()
	await editor(page).locator("input[name=prompt]").fill("a lighthouse in a storm")
	await field(page, "gpt-image-2").click()
	await page.getByRole("option").filter({ hasText: "gpt-image-2.5-flare" }).first().click()
	await page.getByRole("button", { name: "Apply track" }).click()
	await page.getByRole("button", { name: "Save playlist" }).click()
	await expect(page.getByText("Playlist saved")).toBeVisible()
	const saved = JSON.parse(fs.readFileSync(FILE, "utf8")).items.find((x: { title: string }) => x.title === "Pictures").content
	expect(saved).toMatchObject({ dataSource: "ai-image", prompt: "a lighthouse in a storm", randomizePrompt: false, imageSource: "openai-image",
		imageModel: "gpt-image-2.5-flare", quality: "auto", moderation: "auto" })
	// hidden: saved as nothing
	expect(saved.textSource ?? null).toBeNull()
	expect(saved.textModel ?? null).toBeNull()
	watch.expectNone()
})
