import { expect, test, type APIRequestContext, type Page } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// The Gallery page (#517) on the real server: a picture added from this computer is kept, pinned, looked at full screen and removed;
// a picture the panel showed is saved from the Recently shown tab and from the System page. The Gallery is emptied before and after.
test.describe.configure({ mode: "serial" })
const ITEMS = "/api/datasource/gallery/items"

async function empty(request: APIRequestContext) {
	const { items } = await (await request.get(ITEMS)).json()
	for (const item of items) expect((await request.delete(`${ITEMS}/${item.id}`)).ok()).toBeTruthy()
}
test.beforeAll(async ({ request }) => empty(request))
test.afterAll(async ({ request }) => empty(request))
test.beforeEach(async ({ page }) => stubMapTiles(page))

/** A picture drawn in the browser (a PNG of a few colors), as a file to choose. */
async function picture(page: Page, name: string) {
	const base64 = await page.evaluate(() => {
		const canvas = document.createElement("canvas")
		canvas.width = 400
		canvas.height = 300
		const g = canvas.getContext("2d")!
		g.fillStyle = "#c33"
		g.fillRect(0, 0, 400, 300)
		g.fillStyle = "#33c"
		g.fillRect(100, 75, 200, 150)
		return canvas.toDataURL("image/png").split(",")[1]
	})
	return { name, mimeType: "image/png", buffer: Buffer.from(base64, "base64") }
}

test("a picture is added from this computer, pinned, shown full screen and zoomed, and removed", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/gallery")
	await expect(page.getByTestId("gallery-empty")).toBeVisible()
	await page.getByTestId("gallery-file").setInputFiles(await picture(page, "Red and blue.png"))
	await expect(page.getByText("The picture was added to the Gallery.")).toBeVisible()
	const card = page.getByTestId("gallery-grid").getByRole("listitem")
	await expect(card).toHaveCount(1)
	await expect(card).toContainText("Red and blue")
	await expect(card).toContainText("Added by hand")
	await expect(page.getByTestId("gallery-totals")).toContainText("1 of 200 pictures")
	const thumb = card.getByRole("img")
	await expect.poll(() => thumb.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0)

	// pinned: kept when the Gallery is full; the switch shows only the pinned ones
	await card.getByTestId("pin").click()
	await expect(card.getByTestId("pin")).toHaveAttribute("aria-pressed", "true")
	await page.getByTestId("pinned-only").click()
	await expect(card).toHaveCount(1)
	await page.getByTestId("pinned-only").click()

	// full screen, the whole picture; a click shows it at its own size, another fits it again
	await card.getByRole("button", { name: /full size/ }).click()
	const full = page.locator(".viewer img")
	await expect(full).toBeVisible()
	await expect(full).toHaveAttribute("src", /size=full/)
	await expect.poll(() => full.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(400)
	// fitted, the small picture fills the screen; zoomed, it is its own 400 pixels
	const drawn = () => full.evaluate((img: HTMLImageElement) => Math.min(img.getBoundingClientRect().width, img.getBoundingClientRect().height * 4 / 3))
	expect(await drawn()).toBeGreaterThan(400)
	await full.click()
	await expect(page.locator(".viewer.zoomed")).toBeVisible()
	await expect.poll(drawn).toBe(400)
	await full.click()
	await expect(page.locator(".viewer.zoomed")).toHaveCount(0)
	await page.keyboard.press("Escape")
	await expect(full).toBeHidden()

	// removed, once it is confirmed
	await card.getByTestId("remove").click()
	await page.getByRole("alertdialog").getByRole("button", { name: "Remove" }).click()
	await expect(page.getByTestId("gallery-empty")).toBeVisible()
	watch.expectNone()
})

test("what the panel showed is saved to the Gallery from the Recently shown tab, and again from the System page", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/gallery")
	await page.getByRole("tab", { name: "Recently shown" }).click()
	// the mock display drew the playlist's page when the server started
	const recent = page.getByTestId("recent-grid").getByRole("listitem").first()
	await expect(recent).toBeVisible({ timeout: 20000 })
	await recent.getByTestId("save-shown").click()
	await expect(page.getByText(/The picture was added to the Gallery\.|That picture is in the Gallery already\./).first()).toBeVisible()
	await page.getByRole("tab", { name: "Pictures" }).click()
	await expect(page.getByTestId("gallery-grid").getByText("Saved from the panel").first()).toBeVisible()

	// the System page's Now showing has the same button; the picture may be the one just saved
	await page.goto("/#/system")
	await page.getByTestId("save-current").click()
	await expect(page.getByText(/The picture was added to the Gallery\.|That picture is in the Gallery already\./).first()).toBeVisible()
	watch.expectNone()
})
