import { expect, test } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// The Master Prompts (the system prompts of the generators) are device settings: multi-line fields, the fields each may use listed under it, and the factory text
// one click away. Nothing here is saved: the open server's settings stay as the other specs expect.
test.beforeEach(async ({ page }) => stubMapTiles(page))

test("the master prompts list the fields they may use, refuse another, and put back the factory text", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Master Prompts" }).click()
	const request = page.locator("textarea[name=rewriteRequest]")
	await expect(request).toBeVisible()
	// each prompt is a text area; the one that takes a field says which, with what it stands for
	await expect(request).toHaveValue(/Original prompt: "\{prompt\}"/)
	const fields = page.getByTestId("token-list")
	await expect(fields).toHaveCount(1)
	await expect(fields).toContainText("{prompt}")
	await expect(fields).toContainText("The prompt written in the task.")

	// a name the prompt does not list is refused where it is typed
	const factory = await request.inputValue()
	await request.fill(`${factory} {colour}`)
	await request.blur()
	await expect(page.getByText("Unknown field {colour}")).toBeVisible()
	// the factory text comes back from the server's shipped copy, into the field (it is saved, or not, by the user)
	await page.getByRole("button", { name: "Restore default Rewrite a Prompt: Request" }).click()
	await expect(request).toHaveValue(factory)
	await expect(page.getByText("Unknown field {colour}")).toHaveCount(0)

	// the whole tab at once
	const canvas = page.locator("textarea[name=canvas]")
	const canvasFactory = await canvas.inputValue()
	await canvas.fill("something else")
	await page.getByRole("button", { name: "Restore defaults" }).click()
	await expect(canvas).toHaveValue(canvasFactory)
	watch.expectNone()
})
