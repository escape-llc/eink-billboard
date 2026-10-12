import { describe, expect, it } from "vitest"
import { MATERIAL_ICONS, iconClass, installMaterialIcons, materialIconCss, type MaterialIconName } from "./MaterialIcons"

describe("the Material Symbols table", () => {
	it("holds one SVG per name, drawn in the 960 grid so it scales to the text", () => {
		for (const [name, svg] of Object.entries(MATERIAL_ICONS)) {
			expect(svg, name).toMatch(/^<svg [^>]*viewBox="0 -960 960 960"/)
			expect(svg, name).not.toContain("<script")
		}
	})
})

describe("the style sheet", () => {
	it("has .mi and a mi-<name> class per glyph, with hyphens for underscores", () => {
		const css = materialIconCss()
		expect(css).toContain(".mi{display:inline-block")
		expect(css).toContain("flex:none")
		expect(css).toContain("width:var(--mi-size,1rem)")
		for (const name of Object.keys(MATERIAL_ICONS) as MaterialIconName[]) expect(css, name).toContain(`.mi-${name.replaceAll("_", "-")}{--mi-image:url("data:image/svg+xml,`)
		expect(iconClass("skip_next")).toBe("mi-skip-next")
	})
	it("puts the sheet in the page once", () => {
		installMaterialIcons()
		installMaterialIcons()
		expect(document.querySelectorAll("style#material-icons")).toHaveLength(1)
	})
})
