import { expect, test } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// The device theme's typography (body font, heading font, text size) shows as a sample in the fonts the device draws with.
test.beforeEach(async ({ page }) => stubMapTiles(page))

test("the theme tab shows a sample of the chosen fonts, served by the device", async ({ page }) => {
	const watch = watchProblems(page)
	const fonts: string[] = []
	page.on("response", r => { if (r.url().includes("/api/fonts/")) fonts.push(`${r.status()} ${new URL(r.url()).pathname}`) })
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Theme" }).click()
	const sample = page.getByTestId("type-sample")
	await expect(sample).toBeVisible()
	await expect(sample).toHaveCSS("font-family", /eink-Jost/)
	await expect(page.getByText("Body Font", { exact: true }).first()).toBeVisible()
	await expect(page.getByText("Heading Font", { exact: true }).first()).toBeVisible()
	await expect(page.getByText("Text Size", { exact: true }).first()).toBeVisible()
	await expect.poll(() => fonts.filter(f => f.startsWith("200 ")).length).toBeGreaterThan(0)
	watch.expectNone()
})
