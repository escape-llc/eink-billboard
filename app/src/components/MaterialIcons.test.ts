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

// the app's components, views and scripts, as text (as SmallControls.test.ts reads them)
const SOURCES = import.meta.glob<string>(["../**/*.vue", "../**/*.ts", "!../**/*.test.ts", "!./MaterialIcons.ts"], { query: "?raw", import: "default", eager: true })

describe("the app's glyphs", () => {
	it("are all Material Symbols in the table: a class that is not one draws nothing", () => {
		expect(Object.keys(SOURCES).length).toBeGreaterThan(10)
		const known = new Set((Object.keys(MATERIAL_ICONS) as MaterialIconName[]).map(iconClass))
		const unknown: string[] = []
		const used = new Set<string>()
		for (const [file, text] of Object.entries(SOURCES)) {
			for (const m of text.matchAll(/(?<![-\w])mi-([a-z][a-z0-9-]*)/g)) {
				if (m[1] === "size" || m[1] === "image") continue
				used.add(m[1])
				if (!known.has(`mi-${m[1]}`)) unknown.push(`${file}: mi-${m[1]}`)
			}
		}
		// the scan finds them (a pattern that matched nothing would pass)
		expect(used.size).toBeGreaterThan(40)
		expect(unknown).toEqual([])
	})
	it("are one set: no PrimeIcons class (#544)", () => {
		const prime = Object.entries(SOURCES).flatMap(([file, text]) => [...text.matchAll(/\bpi pi-[a-z-]+|["'`]pi-[a-z-]+/g)].map(m => `${file}: ${m[0]}`))
		expect(prime).toEqual([])
	})
})
