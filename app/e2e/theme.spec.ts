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

test("the theme tab has a selector for each font and a swatch for every color of the palette", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Theme" }).click()
	// the fonts are chosen from the ones the device ships
	await page.getByRole("tabpanel").locator(".p-select").filter({ hasText: "Jost" }).first().click()
	await expect(page.getByRole("option")).toHaveText(["Jost", "Napoli", "Dogica (pixel)", "DS-Digital (segments)"])
	await page.getByRole("option", { name: "Napoli" }).click()
	await expect(page.getByTestId("type-sample")).toHaveCSS("font-family", /eink-Napoli/)
	// 5 tones of 3 colors
	const swatches = page.getByTestId("palette").locator(".swatch")
	await expect(swatches).toHaveCount(15)
	await expect.poll(async () => (await swatches.evaluateAll(els => els.map(e => getComputedStyle(e).backgroundColor))).filter(c => c !== "rgba(0, 0, 0, 0)").length).toBe(15)
	// the colors follow the form
	const before = await page.locator("[data-role=text-primary]").evaluate(e => getComputedStyle(e).backgroundColor)
	const hue = page.getByRole("spinbutton", { name: "Hue" })
	await hue.fill(String((Number(await hue.inputValue()) + 90) % 360))
	await hue.blur()
	await expect.poll(() => page.locator("[data-role=text-primary]").evaluate(e => getComputedStyle(e).backgroundColor)).not.toBe(before)
	watch.expectNone()
})
