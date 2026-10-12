import { expect, test } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

test.beforeEach(async ({ page }) => stubMapTiles(page))

// the row a form field renders into: its label plus the control(s)
const row = (page: import("@playwright/test").Page, label: string) =>
	page.locator(".p-inputgroup").filter({ has: page.locator("label", { hasText: label }) })

test("a boolean field is one toggle, not a toggle followed by a text box", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Display" }).click()
	const rotate = row(page, "Rotate 180")
	await expect(rotate).toHaveCount(1)
	await expect(rotate.locator(".p-toggleswitch")).toHaveCount(1)
	await expect(rotate.locator("input[type=text]")).toHaveCount(0)
	watch.expectNone()
})

test("a field shown only when another is on: hidden until then, required while shown, saved as null when hidden again", async ({ page, request }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Display" }).click()
	const detail = page.getByPlaceholder("E2E Detail")
	const save = page.getByRole("tabpanel").locator("button:has(.pi-check)").first()
	const toggle = row(page, "E2E Advanced").locator(".p-toggleswitch")
	await expect(toggle).toBeVisible()
	await expect(detail).toHaveCount(0)

	await toggle.click()
	await expect(detail).toBeVisible()
	// shown and required, so empty is invalid and the form does not save
	await detail.focus()
	await detail.blur()
	await expect(page.getByText("Required", { exact: true })).toBeVisible()
	await detail.fill("some detail")
	await expect(save).toBeEnabled()
	await save.click()
	await expect(page.getByText("Settings saved successfully")).toBeVisible()
	expect((await (await request.get("/api/settings/display")).json()).e2eDetail).toBe("some detail")

	// hidden again: no longer required, and what it held is not kept
	await toggle.click()
	await expect(detail).toHaveCount(0)
	await expect(save).toBeEnabled()
	await save.click()
	const display = async () => (await request.get("/api/settings/display")).json()
	await expect.poll(async () => (await display()).e2eAdvanced).toBe(false)
	expect((await display()).e2eDetail).toBeNull()
	watch.expectNone()
})

test("the playlist track form renders the plugin's fields and follows a change of plugin", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/playlist")
	await page.getByText("Morning slides").first().click()
	const editor = page.locator(".track-editor")
	// a form that failed to build would be an empty card
	await expect(editor.locator("label", { hasText: "Title" })).toBeVisible()
	await expect(editor.locator("label", { hasText: "Max Slides" })).toBeVisible()
	await expect(editor.getByRole("spinbutton").first()).toBeVisible()

	// a track plays on the background or foreground layer: only the playlist plugins are offered, not the timer ones (Priority Update, Overlay)
	await editor.locator(".p-select").filter({ hasText: "Slide Show" }).first().click()
	await expect(page.getByRole("option")).toHaveCount(1)
	await expect(page.getByRole("option").filter({ hasText: "Slide Show" })).toBeVisible()
	await page.keyboard.press("Escape")
	watch.expectNone()
})

test("a list of rows: add, edit and reorder rows, a repeated name is refused on its row, and the list is saved", async ({ page, request }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Display" }).click()
	const save = page.getByRole("tabpanel").locator("button:has(.pi-check)").first()
	const add = page.getByRole("button", { name: "Add to E2E Feeds" })
	await add.click()
	await page.getByRole("textbox", { name: "Name 1", exact: true }).fill("first")
	await page.getByRole("textbox", { name: "URL 1", exact: true }).fill("http://first.example/feed")
	// a row's controls fill their cells (inside an input group PrimeVue gives inputs `width: 1%`, which once left them a few pixels wide)
	const wide = async (name: string) => expect((await page.getByRole("textbox", { name, exact: true }).boundingBox())!.width).toBeGreaterThan(120)
	await wide("Name 1")
	await wide("URL 1")
	await add.click()
	await page.getByRole("textbox", { name: "Name 2", exact: true }).fill("first")
	// the name identifies a row, so a repeat is refused where it was typed and nothing can be saved
	await expect(page.getByText("Must be unique")).toBeVisible()
	await expect(save).toBeDisabled()
	await page.getByRole("textbox", { name: "Name 2", exact: true }).fill("second")
	await page.getByRole("textbox", { name: "URL 2", exact: true }).fill("ftp://second.example")
	await expect(page.getByText("Enter a valid URL")).toBeVisible()
	await page.getByRole("textbox", { name: "URL 2", exact: true }).fill("https://second.example")
	await expect(save).toBeEnabled()
	// the second row moves above the first
	await page.getByRole("button", { name: "Move 2 up" }).click()
	await expect(page.getByRole("textbox", { name: "Name 1", exact: true })).toHaveValue("second")
	await save.click()
	await expect(page.getByText("Settings saved successfully")).toBeVisible()
	const stored = async () => (await (await request.get("/api/settings/display")).json()).e2eFeeds
	expect(await stored()).toEqual([{ name: "second", url: "https://second.example" }, { name: "first", url: "http://first.example/feed" }])

	// what was saved comes back, and a row can be removed
	await page.reload()
	await page.getByRole("tab", { name: "Display" }).click()
	await expect(page.getByRole("textbox", { name: "Name 2", exact: true })).toHaveValue("first")
	await page.getByRole("button", { name: "Remove 1" }).click()
	await expect(save).toBeEnabled()
	await save.click()
	await expect.poll(stored).toEqual([{ name: "first", url: "http://first.example/feed" }])
	watch.expectNone()
})

test("an address is checked as one, and its Test button asks the server (and only for a valid address)", async ({ page }) => {
	const watch = watchProblems(page)
	const asked: unknown[] = []
	let answer = { ok: true, message: "6 stories" }
	await page.route("**/api/e2e/test-url", async route => {
		asked.push(route.request().postDataJSON())
		await route.fulfill({ json: answer })
	})
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Display" }).click()
	const url = page.getByPlaceholder("E2E URL")
	const test = page.getByRole("button", { name: "Test E2E URL" })
	await expect(url).toHaveAttribute("type", "url")
	await expect(test).toBeDisabled()
	await url.fill("not an address")
	await url.blur()
	await expect(page.getByText("Enter a valid URL")).toBeVisible()
	await expect(test).toBeDisabled()

	await url.fill("https://feed.example.test/rss")
	await expect(test).toBeEnabled()
	await test.click()
	await expect(page.getByText("6 stories")).toBeVisible()
	// the server is told the address; the page itself does not fetch it
	expect(asked).toEqual([{ value: "https://feed.example.test/rss" }])
	// an answer is about the address that was sent: editing it clears the answer
	await url.fill("https://feed.example.test/other")
	await expect(page.getByText("6 stories")).toHaveCount(0)
	answer = { ok: false, message: "Not a feed" }
	await test.click()
	await expect(page.getByText("Not a feed")).toBeVisible()
	watch.expectNone()
})

test("a row of a list has its own Test button", async ({ page }) => {
	const watch = watchProblems(page)
	await page.route("**/api/e2e/test-url", route => route.fulfill({ json: { ok: true, message: "reachable" } }))
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Display" }).click()
	// rows saved by an earlier test may be there: the new one is the next
	const number = (await page.getByRole("textbox", { name: /^Name \d+$/ }).count()) + 1
	await page.getByRole("button", { name: "Add to E2E Feeds" }).click()
	await page.getByRole("textbox", { name: `Name ${number}`, exact: true }).fill("one more")
	const test = page.getByRole("button", { name: `Test URL ${number}` })
	await expect(test).toBeDisabled()
	await page.getByRole("textbox", { name: `URL ${number}`, exact: true }).fill("https://one.example.test/feed")
	await test.click()
	await expect(page.getByText("reachable")).toBeVisible()
	watch.expectNone()
})
