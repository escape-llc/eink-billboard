import { describe, expect, it } from "vitest"
import { sectionProblems } from "./DescriptorSchema"

// every descriptor of the repository (data sources, plugins, displays) and every NVE schema: read when the tests run, so the type-check needs none of them
const descriptors = import.meta.glob<Record<string, unknown>>("../../../python/{datasources,plugins,displays}/*/*-info.json", { eager: true, import: "default" })
const nveSchemas = import.meta.glob<Record<string, unknown>>("../../../python/storage/schemas/*.json", { eager: true, import: "default" })

/** Each settings section to check, named by its file (and section). */
function sections(): [string, unknown][] {
	const retv: [string, unknown][] = []
	for (const [path, info] of Object.entries(descriptors)) {
		const file = path.replace(/^(\.\.\/)+/, "")
		for (const key of ["settings", "instanceSettings"]) {
			if (key in info) retv.push([`${file}#${key}`, info[key]])
		}
	}
	for (const [path, schema] of Object.entries(nveSchemas)) retv.push([path.replace(/^(\.\.\/)+/, ""), schema])
	return retv
}

describe("every descriptor is one the form can read (DescriptorSchema.ts)", () => {
	it("finds the descriptors and the NVE schemas", () => {
		expect(Object.keys(descriptors).length).toBeGreaterThan(30)
		expect(Object.keys(nveSchemas).length).toBeGreaterThanOrEqual(5)
	})
	it.each(sections())("%s", (where, section) => {
		expect(sectionProblems(section, where)).toEqual([])
	})
})

/** A real section to break: the Image Folder's settings (a list of rows) with a lookup added that a field names. */
function aSection() {
	const [, info] = Object.entries(descriptors).find(([path]) => path.includes("/image_folder/"))!
	const section = structuredClone(info.settings) as any
	section.schema.lookups = { ...(section.schema.lookups ?? {}), choice: { items: [{ name: "A", value: "a" }] } }
	section.schema.properties.push({ name: "picked", title: "Picked", type: "string", required: false, default: null, lookup: "choice" })
	return section
}

/** The second field of the section's list rows chooses from `lookup`. */
function rowLookup(s: any, lookup: object) {
	s.schema.lookups.rowChoice = lookup
	s.schema.properties.find((p: any) => p.type === "array").items.properties[1].lookup = "rowChoice"
}

describe("a broken descriptor is caught", () => {
	it("the copy to break is a good one", () => {
		expect(sectionProblems(aSection(), "copy")).toEqual([])
	})
	it("a lookup sent with other fields, and a search, where they belong are good", () => {
		const section = aSection()
		section.schema.lookups.choice = { url: "/x", with: ["folders"], search: true }
		rowLookup(section, { url: "/y", with: ["name"] })
		expect(sectionProblems(section, "copy")).toEqual([])
	})
	const breaks: [string, (s: any) => void, RegExp][] = [
		["a misspelled keyword", s => { s.schema.properties.at(-1).minLenght = 3 }, /properties\/\d+: Unrecognized key: "minLenght"/],
		["an unknown type", s => { s.schema.properties.at(-1).type = "strng" }, /properties\/\d+/],
		["an unknown format", s => { s.schema.properties.at(-1).format = "multi-line" }, /properties\/\d+\/format/],
		["a property without its title", s => { delete s.schema.properties.at(-1).title }, /properties\/\d+\/title/],
		["a lookup of no known kind", s => { s.schema.lookups.choice = { choices: ["a"] } }, /lookups\/choice/],
		["a field naming a lookup that is not defined", s => { s.schema.properties.at(-1).lookup = "chioce" }, /properties\/\d+\/lookup: "chioce" is not one of the schema's lookups/],
		["a row field naming a lookup that is not defined", s => { s.schema.properties.find((p: any) => p.type === "array").items.properties[0].lookup = "nowhere" }, /items\/properties\/0\/lookup: "nowhere"/],
		["a list inside a row", s => { s.schema.properties.find((p: any) => p.type === "array").items.properties[0].type = "array" }, /items\/properties\/0\/type/],
		["an unknown key in the section", s => { s.defaults = {} }, /^copy: Unrecognized key: "defaults"/],
		// a lookup with parameters (#510 A8): `with` names other fields where it is used, a row has no search box
		["a lookup sent with no field", s => { s.schema.lookups.choice = { url: "/x", with: [] } }, /lookups\/choice/],
		["a lookup sent with a field that is not there", s => { s.schema.lookups.choice = { url: "/x", with: ["nowhere"] } }, /"choice" is sent with "nowhere", which is not another field of the schema/],
		["a lookup sent with its own field", s => { s.schema.lookups.choice = { url: "/x", with: ["picked"] } }, /"choice" is sent with "picked"/],
		["a row lookup sent with a field outside the row", s => { rowLookup(s, { url: "/x", with: ["picked"] }) }, /items\/properties\/1\/lookup: "rowChoice" is sent with "picked", which is not another field of the row/],
		["a search in a row", s => { rowLookup(s, { url: "/x", search: true }) }, /items\/properties\/1\/lookup: "rowChoice" is a search, which a list row cannot have/],
	]
	it.each(breaks)("%s", (_, breakIt, expected) => {
		const section = aSection()
		breakIt(section)
		const problems = sectionProblems(section, "copy")
		expect(problems.some(p => expected.test(p)), problems.join("\n")).toBe(true)
	})
})
