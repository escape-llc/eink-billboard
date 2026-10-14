import { describe, expect, it } from "vitest"

// Every PrimeVue control that has sizes is the small one, so a page's controls line up (a normal Select beside small buttons is taller).
const SIZED = ["Button", "InputText", "InputNumber", "Select", "MultiSelect", "DatePicker", "Textarea", "Password", "SelectButton", "AutoComplete", "Message"]
// the app's components and views, as text (Vite reads them; no Node API, so the app's type-check covers this file too)
const SOURCES = import.meta.glob<string>("../**/*.vue", { query: "?raw", import: "default", eager: true })

describe("PrimeVue controls", () => {
	it("are all size small", () => {
		expect(Object.keys(SOURCES).length).toBeGreaterThan(10)
		const unsized: string[] = []
		for (const [file, text] of Object.entries(SOURCES)) {
			for (const m of text.matchAll(new RegExp(`<(${SIZED.join("|")})\\b([^>]*?)/?>`, "gs"))) {
				if (!/\bsize="small"/.test(m[2] ?? "")) unsized.push(`${file}: <${m[1]}>`)
			}
		}
		expect(unsized).toEqual([])
	})
})
