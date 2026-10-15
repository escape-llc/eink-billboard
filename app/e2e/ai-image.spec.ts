import fs from "node:fs"
import path from "node:path"
import { expect, test, type Page } from "@playwright/test"
import { OPEN } from "./servers"
import { stubMapTiles, watchProblems } from "./support"

// A Generated Image chooses its parts (a text source, an image source), and each part's fields show under its choice, in the one track.
// The providers' lookups are answered here, in the browser: the test never reaches OpenAI or Google.
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
async function stubProviders(page: Page) {
	await page.route("**/api/datasource/openai/lookups/image-models", route => route.fulfill({ json: choices("gpt-image-2.5-flare", "gpt-image-2", "gpt-image-1.5") }))
	await page.route("**/api/datasource/openai/lookups/text-models", route => route.fulfill({ json: choices("gpt-5.6-sol", "gpt-5.6-luna") }))
	await page.route("**/api/datasource/openai/lookups/qualities", route => route.fulfill({ json: [{ name: "Auto (the model chooses)", value: "auto" }, { name: "High", value: "high" }] }))
	await page.route("**/api/datasource/google-ai/lookups/image-models", route => route.fulfill({ json: choices("gemini-nano-banana-2.1", "gemini-3-pro-image") }))
	await page.route("**/api/datasource/google-ai/lookups/text-models", route => route.fulfill({ json: choices("gemini-3.5-flash") }))
	await page.route("**/api/datasource/google-ai/lookups/qualities", route => route.fulfill({ json: [{ name: "Auto (1K)", value: "auto" }, { name: "High (2K)", value: "high" }] }))
}

test.beforeEach(async ({ page }) => {
	restore()
	await stubMapTiles(page)
	await stubProviders(page)
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

test("choosing a Google image source swaps that part's fields, and GPT text goes with it", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/playlist")
	await page.getByRole("button", { name: "Add track" }).click()
	await editor(page).locator("input[type=text]").first().fill("Mixed")
	await field(page, "Data Source").click()
	await page.getByRole("option").filter({ hasText: "Generated Image" }).first().click()
	await expect(editor(page).getByText("Moderation", { exact: true })).toBeVisible()
	await editor(page).locator("input[name=prompt]").fill("a lighthouse")
	// the image part is Google's now: its model list, no OpenAI-only field; the text part stays OpenAI's
	await field(page, "OpenAI Image").click()
	await page.getByRole("option").filter({ hasText: "Google Image" }).first().click()
	await expect(editor(page).getByText("Moderation", { exact: true })).toBeHidden()
	await expect(field(page, "gemini-nano-banana-2.1")).toBeVisible()
	await expect(editor(page).getByText("Text Model", { exact: true })).toBeVisible()
	await field(page, "gemini-nano-banana-2.1").click()
	await page.getByRole("option").filter({ hasText: "gemini-3-pro-image" }).first().click()
	await page.getByRole("button", { name: "Apply track" }).click()
	await page.getByRole("button", { name: "Save playlist" }).click()
	await expect(page.getByText("Playlist saved")).toBeVisible()
	const saved = JSON.parse(fs.readFileSync(FILE, "utf8")).items.find((x: { title: string }) => x.title === "Mixed").content
	expect(saved).toMatchObject({ dataSource: "ai-image", imageSource: "google-image", imageModel: "gemini-3-pro-image", quality: "auto", textSource: "openai-text", textModel: "gpt-5.6-luna" })
	// the previous part's own field is not saved with the new one
	expect(saved.moderation ?? null).toBeNull()
	watch.expectNone()
})
