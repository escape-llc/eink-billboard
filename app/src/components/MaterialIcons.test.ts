import { describe, expect, it } from "vitest"
import { MATERIAL_ICONS } from "./MaterialIcons"

describe("the Material Symbols table", () => {
	it("holds one SVG per name, drawn in the 960 grid so it scales to the text", () => {
		for (const [name, svg] of Object.entries(MATERIAL_ICONS)) {
			expect(svg, name).toMatch(/^<svg [^>]*viewBox="0 -960 960 960"/)
			expect(svg, name).not.toContain("<script")
		}
	})
})
