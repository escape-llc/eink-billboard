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

test("the theme tab has a selector for each font and a swatch for every role of the palette", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Theme" }).click()
	// the fonts are chosen from the ones the device ships
	await page.getByRole("tabpanel").locator(".p-select").filter({ hasText: "Jost" }).first().click()
	await expect(page.getByRole("option")).toHaveText(["Jost", "Atkinson Hyperlegible", "Lexend", "League Spartan", "Literata (serif)", "Bitter (slab serif)", "Dogica (pixel)", "DSEG7 (segments)"])
	await page.getByRole("option", { name: "Atkinson Hyperlegible" }).click()
	await expect(page.getByTestId("type-sample")).toHaveCSS("font-family", /eink-Atkinson Hyperlegible/)
	// the device resolves each role to an ink of the attached panel, and says which panel that is
	await expect(page.getByTestId("ink-set")).toContainText("Shown for: Six colors (Spectra 6)")
	const swatches = page.getByTestId("palette").locator(".swatch")
	await expect(swatches).toHaveCount(9)
	await expect(page.locator("[data-role=text-secondary-1]")).toHaveCSS("background-color", "rgb(247, 112, 116)")
	// choosing another preset changes the colors
	const before = await page.locator("[data-role=text-secondary-1]").evaluate(e => getComputedStyle(e).backgroundColor)
	await page.getByRole("tabpanel").locator(".p-select").filter({ hasText: "Classic" }).first().click()
	await page.getByRole("option", { name: /^Mono/ }).click()
	await expect.poll(() => page.locator("[data-role=text-secondary-1]").evaluate(e => getComputedStyle(e).backgroundColor)).not.toBe(before)
	watch.expectNone()
})

test("the theme tab has a mock-up of a page in the theme's colors, fonts and size", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Theme" }).click()
	const mock = page.getByTestId("mockup")
	await expect(mock).toBeVisible()
	// the title wears the palette's text-primary, as the swatch of that role shows
	const swatch = page.locator("[data-role=text-primary]")
	await expect.poll(() => swatch.evaluate(e => getComputedStyle(e).backgroundColor)).not.toBe("rgba(0, 0, 0, 0)")
	const want = await swatch.evaluate(e => getComputedStyle(e).backgroundColor)
	await expect(mock.locator(".mock-light .mock-title")).toHaveCSS("color", want)
	await expect(mock.locator(".mock-light .mock-title")).toHaveCSS("font-family", /eink-Jost/)
	// the text size multiplies the mock-up's text
	const size = async () => parseFloat(await mock.locator(".mock-light .mock-title").evaluate(e => getComputedStyle(e).fontSize))
	const before = await size()
	const scale = page.getByRole("spinbutton", { name: "Text Size" })
	await scale.fill("1.4")
	await scale.blur()
	await expect.poll(size).toBeGreaterThan(before * 1.3)
	watch.expectNone()
})

test("the page background is white unless it is changed, and black is dark mode", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Theme" }).click()
	const pageSwatch = page.locator(".swatch[data-role=bg-page]")
	// the overlays' outline follows the page: white, black on a black page
	const outlineSwatch = page.locator(".swatch[data-role=text-outline]")
	await expect.poll(() => outlineSwatch.evaluate(e => getComputedStyle(e).backgroundColor)).toBe("rgb(255, 255, 255)")
	await expect.poll(() => pageSwatch.evaluate(e => getComputedStyle(e).backgroundColor)).toBe("rgb(255, 255, 255)")
	await expect(page.getByTestId("mockup").locator(".mock-light")).toHaveCSS("background-color", "rgb(255, 255, 255)")
	await page.getByRole("tabpanel").locator(".p-select").filter({ hasText: "White" }).first().click()
	await expect(page.getByRole("option")).toHaveText(["White", "Black (dark mode)"])
	await page.getByRole("option", { name: "Black (dark mode)" }).click()
	await expect.poll(() => pageSwatch.evaluate(e => getComputedStyle(e).backgroundColor)).toBe("rgb(0, 0, 0)")
	await expect.poll(() => outlineSwatch.evaluate(e => getComputedStyle(e).backgroundColor)).toBe("rgb(0, 0, 0)")
	await expect(page.getByTestId("mockup").locator(".mock-light")).toHaveCSS("background-color", "rgb(0, 0, 0)")
	watch.expectNone()
})

test("a custom preset offers an ink for each role", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Theme" }).click()
	await expect(page.getByText("Main Text Ink", { exact: true })).toHaveCount(0)
	await page.getByRole("tabpanel").locator(".p-select").filter({ hasText: "Classic" }).first().click()
	await page.getByRole("option", { name: /^Custom/ }).click()
	for(const title of ["Main Text Ink", "First Accent Ink", "Second Accent Ink", "Highlight Ink", "Highlight Text Ink"]) await expect(page.getByText(title, { exact: true }).first()).toBeVisible()
	watch.expectNone()
})
