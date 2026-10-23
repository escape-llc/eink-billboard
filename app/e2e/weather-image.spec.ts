import { expect, test, type Page } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// A Weather Visualizer track: a prompt that talks about the weather. The data that supplies the values (OpenWeatherMap) says which fields the prompt may use, and the form
// lists them under it and refuses any other. Nothing is saved; the providers' lookups are answered here, in the browser.
const choices = (...values: string[]) => values.map(value => ({ name: value, value }))
async function stubProviders(page: Page) {
	await page.route("**/api/datasource/openai-api/lookups/image-models", route => route.fulfill({ json: choices("gpt-image-2") }))
	await page.route("**/api/datasource/openai-api/lookups/text-models", route => route.fulfill({ json: choices("gpt-5.6-sol") }))
	await page.route("**/api/datasource/openai-api/lookups/qualities", route => route.fulfill({ json: [{ name: "Auto (the model chooses)", value: "auto" }] }))
}
test.beforeEach(async ({ page }) => {
	await stubMapTiles(page)
	await stubProviders(page)
})

test("the prompt lists the weather fields OpenWeatherMap supplies, and refuses another", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/playlist")
	await page.getByRole("button", { name: "Add track" }).click()
	const editor = page.locator(".track-editor")
	await editor.locator(".p-select").filter({ hasText: "Data Source" }).first().click()
	await page.getByRole("option").filter({ hasText: "Weather Visualizer" }).first().click()
	const prompt = editor.locator("textarea[name=weatherPrompt]")
	await expect(prompt).toHaveValue(/A bold, flat-color illustration of \{place\}/)
	// thirteen fields: the list starts closed, and opens from its summary
	const fields = editor.getByTestId("token-list").first()
	await expect(fields).toBeHidden()
	await editor.getByText("Fields you may use (13)").click()
	await expect(fields).toBeVisible()
	for (const name of ["place", "condition", "temp", "daypart", "season", "sunrise", "rain"]) await expect(fields).toContainText(`{${name}}`)
	await expect(fields).toContainText("The temperature now, with its unit")
	// the fields of the text part and the image part are the Generated Image's: chosen separately, and the rewrite is off until asked for
	await expect(editor.getByText("Image Source", { exact: true })).toBeVisible()
	await expect(editor.getByText("Text Source", { exact: true })).toHaveCount(0)

	await prompt.fill("A poster of {place} with {fog}")
	await prompt.blur()
	await expect(editor.getByText("Unknown field {fog}")).toBeVisible()
	await expect(page.getByRole("button", { name: "Apply track" })).toBeDisabled()
	await prompt.fill("A poster of {place} with {condition}")
	await prompt.blur()
	await expect(editor.getByText("Unknown field")).toHaveCount(0)
	watch.expectNone()
})
