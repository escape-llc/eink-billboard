import { expect, test } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// The Slide Show's list settings (Slides in a List, Fetch Again After) mean something only for a data source whose list outlasts a visit (a feed, a folder, a comic):
// a picture of the day has no list, so they are not shown for it (the form reads the chosen source's `keepsList`).
test.beforeEach(async ({ page }) => stubMapTiles(page))

test("the list settings are shown for a source with a list and not for a picture of the day", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/playlist")
	await page.getByRole("button", { name: "Add track" }).click()
	const editor = page.locator(".track-editor")
	const choose = async (name: string) => {
		// the plugin is the first choice, the data source the second (its text is the source chosen, once there is one)
		await editor.locator(".p-select").nth(1).click()
		await page.getByRole("option").filter({ hasText: name }).first().click()
	}
	const listMode = editor.getByText("Slides in a List", { exact: true })
	const refresh = editor.getByText("Fetch Again After", { exact: true })

	await choose("NASA Picture of the Day")
	await expect(editor.getByText("Slide Duration", { exact: true })).toBeVisible()
	// one picture: the count is 1, so it is not asked
	const maxSlides = editor.getByText("Max Slides", { exact: true })
	await expect(maxSlides).toHaveCount(0)
	await expect(listMode).toHaveCount(0)
	await expect(refresh).toHaveCount(0)

	await choose("Comic")
	await expect(maxSlides).toBeVisible()
	await expect(listMode).toBeVisible()
	await expect(refresh).toBeVisible()

	// the choice of mode decides the second, as before
	await editor.locator(".p-select").filter({ hasText: "continue" }).first().click()
	await page.getByRole("option", { name: "restart" }).click()
	await expect(refresh).toHaveCount(0)

	await choose("NASA Picture of the Day")
	await expect(listMode).toHaveCount(0)
	watch.expectNone()
})
