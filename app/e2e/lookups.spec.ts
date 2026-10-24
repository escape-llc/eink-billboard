import { expect, test } from "@playwright/test"
import { OPEN } from "./servers"
import { stubMapTiles, watchProblems } from "./support"

// Regression for #43: lookups were requested from http://api/... and the dropdowns stayed empty.
test("the Timezone and Locale lists are loaded from this server", async ({ page }) => {
	await stubMapTiles(page)
	const watch = watchProblems(page)
	const lookups: string[] = []
	page.on("request", r => { if (r.url().includes("/lookups/")) lookups.push(r.url()) })
	await page.goto("/#/settings")

	await page.locator(".p-select").filter({ hasText: "New York" }).first().click()
	// every region/city zone, well over a hundred
	expect(await page.getByRole("option").count()).toBeGreaterThan(100)
	await page.keyboard.press("Escape")

	await page.locator(".p-select").filter({ hasText: "English" }).first().click()
	await expect(page.getByRole("option")).toHaveCount(4)
	await expect(page.getByRole("option").filter({ hasText: "Français" })).toBeVisible()

	expect(lookups.length).toBeGreaterThan(0)
	for (const url of lookups) expect(url.startsWith(`${OPEN.url}/api/lookups/`), url).toBe(true)
	watch.expectNone()
})

// A lookup that takes parameters (#510 A8): the Generated Image's quality is asked with the chosen model (`with`), the Newspaper is searched (`search`).
// The quality and newspaper routes are the real server's; the model list (which needs an OpenAI key) is answered here.
const choices = (...values: string[]) => values.map(value => ({ name: value, value }))
async function addTrack(page: import("@playwright/test").Page, source: string) {
	await page.goto("/#/playlist")
	await page.getByRole("button", { name: "Add track" }).click()
	await page.locator(".track-editor .p-select").filter({ hasText: "Data Source" }).first().click()
	await page.getByRole("option").filter({ hasText: source }).first().click()
}

test("the qualities are asked for with the chosen image model, and asked again when it changes", async ({ page }) => {
	await stubMapTiles(page)
	await page.route("**/api/datasource/openai-api/lookups/image-models", route => route.fulfill({ json: choices("gpt-image-2.5-flare", "gpt-image-2") }))
	await page.route("**/api/datasource/openai-api/lookups/text-models", route => route.fulfill({ json: choices("gpt-5.6-luna") }))
	await page.route("**/api/datasource/google-api/lookups/*", route => route.fulfill({ json: [] }))
	const watch = watchProblems(page)
	const asked: string[] = []
	page.on("request", r => { if (r.url().includes("/lookups/qualities")) asked.push(new URL(r.url()).search) })
	await addTrack(page, "Generated Image")
	const quality = page.locator(".track-editor .p-select").filter({ hasText: "Auto (the model chooses)" }).first()
	await expect(quality).toBeVisible()
	await expect.poll(() => asked).toEqual(["?imageModel=gpt-image-2"])
	await quality.click()
	await expect(page.getByRole("option").filter({ hasText: "High" })).toHaveCount(1)
	await expect(page.getByRole("option").filter({ hasText: "Maximum" })).toHaveCount(0)
	await page.keyboard.press("Escape")

	await page.locator(".track-editor .p-select").filter({ hasText: "gpt-image-2" }).first().click()
	await page.getByRole("option").filter({ hasText: "gpt-image-2.5-flare" }).first().click()
	await expect.poll(() => asked.at(-1)).toBe("?imageModel=gpt-image-2.5-flare")
	await quality.click()
	await expect(page.getByRole("option").filter({ hasText: "Maximum (gpt-image-2.5)" })).toHaveCount(1)
	await page.keyboard.press("Escape")
	watch.expectNone()
})

test("a search lookup asks only when a search is made, and its answer is the choice's list", async ({ page }) => {
	await stubMapTiles(page)
	const watch = watchProblems(page)
	const asked: string[] = []
	page.on("request", r => { if (r.url().includes("/lookups/newspaperSlug")) asked.push(new URL(r.url()).searchParams.get("q") ?? "(none)") })
	await addTrack(page, "Newspaper")
	// the stored choice (the default) is asked for by its value, so it shows its name; nothing else was fetched
	const paper = page.locator(".track-editor .p-select").filter({ hasText: "The New York Times" }).first()
	await expect(paper).toBeVisible()
	expect(asked).toEqual(["ny_nyt"])
	const box = page.getByRole("textbox", { name: "Search Newspaper" })
	// typing sends nothing; Enter does
	await box.fill("colorado springs")
	await page.waitForTimeout(500)
	expect(asked).toEqual(["ny_nyt"])
	await box.press("Enter")
	await expect.poll(() => asked.at(-1)).toBe("colorado springs")
	await paper.click()
	await page.getByRole("option").filter({ hasText: "The Gazette" }).first().click()
	await expect(page.locator(".track-editor .p-select").filter({ hasText: "The Gazette" }).first()).toBeVisible()

	await box.fill("no paper is called this")
	await page.getByRole("button", { name: "Search for Newspaper" }).click()
	await expect(page.getByTestId("lookup-hint")).toHaveText('Nothing found for "no paper is called this".')
	// the choice made is still there, though the last search did not find it
	await expect(page.locator(".track-editor .p-select").filter({ hasText: "The Gazette" }).first()).toBeVisible()
	watch.expectNone()
})
