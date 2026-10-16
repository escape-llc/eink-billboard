import { describe, expect, it } from "vitest"
import { derivedValues, evaluate, findProblems, hiddenNames } from "./FormVisibility"
import type { FormField } from "./FormValidation"
import cases from "../../../python/tests/form_visibility.json"

describe("shared visibility cases (form_visibility.json)", () => {
	for (const c of cases.cases) {
		it(c.name, () => expect(evaluate(c.predicate, c.values)).toBe(c.visible))
	}
})

const f = (name: string, extra: Record<string, unknown> = {}) => ({ name, title: name, type: "string", required: false, ...extra }) as FormField

describe("hiddenNames", () => {
	it("hides the fields whose predicate fails, and the children of a hidden schema field", () => {
		const fields = [
			f("randomize", { type: "boolean" }),
			f("custom", { visibleIf: { field: "randomize", const: false } }),
			f("source", { type: "schema", visibleIf: { field: "randomize", const: false }, children: [f("folder")] }),
		]
		expect([...hiddenNames(fields, { randomize: true })].sort()).toEqual(["custom", "folder", "source"])
		expect([...hiddenNames(fields, { randomize: false })]).toEqual([])
	})
	it("reads values through a getter too (the form's field state)", () => {
		const fields = [f("a", { visibleIf: { field: "b", const: 1 } })]
		expect(hiddenNames(fields, (n) => (n === "b" ? 1 : undefined)).size).toBe(0)
	})
})

describe("findProblems", () => {
	it("accepts a good descriptor", () => {
		expect(findProblems([f("a", { type: "boolean" }), f("b", { visibleIf: { field: "a", const: true } })])).toEqual([])
	})
	it("reports unknown fields, malformed predicates and cycles", () => {
		expect(findProblems([f("b", { visibleIf: { field: "nope", const: 1 } })])[0]).toMatch(/unknown field 'nope'/)
		expect(findProblems([f("b", { visibleIf: { field: "b" } })]).join()).toMatch(/needs const, enum, set or contains/)
		expect(findProblems([f("a", { visibleIf: { field: "b", set: true } }), f("b", { visibleIf: { field: "a", set: true } })]).join()).toMatch(/cycle: a -> b -> a|cycle: b -> a -> b/)
	})
})

describe("values derived from the source a schema field chose", () => {
	// what the form offers a data source field: each choice carries its source's features and whether its list outlasts a visit
	const source = (list: { value: string, features: string[], keepsList: boolean }[]) => f("dataSource", { type: "schema", list } as Partial<FormField>)
	const fields = [
		source([{ value: "feed", features: ["media-list"], keepsList: true }, { value: "day", features: ["media-image"], keepsList: false }]),
		f("listMode", { visibleIf: { field: "dataSource.keepsList", const: true } }),
		f("listy", { visibleIf: { field: "dataSource.features", contains: "media-list" } }),
	]
	it("reads the chosen source's features and whether it keeps its list", () => {
		const read = derivedValues(fields, { dataSource: "feed" })
		expect([read("dataSource.features"), read("dataSource.keepsList"), read("dataSource")]).toEqual([["media-list"], true, "feed"])
		const none = derivedValues(fields, (name) => (name === "dataSource" ? "day" : undefined))
		expect([none("dataSource.features"), none("dataSource.keepsList")]).toEqual([["media-image"], false])
		const unset = derivedValues(fields, {})
		expect([unset("dataSource.features"), unset("dataSource.keepsList")]).toEqual([[], false])
		// a name that is not a derived one, or whose base is not a schema field, is read as it is
		expect(derivedValues(fields, { "listMode.features": 3 })("listMode.features")).toBe(3)
	})
	it("hides what only a list source needs", () => {
		expect([...hiddenNames(fields, { dataSource: "feed" })]).toEqual([])
		expect([...hiddenNames(fields, { dataSource: "day" })].sort()).toEqual(["listMode", "listy"])
		expect([...hiddenNames(fields, {})].sort()).toEqual(["listMode", "listy"])
	})
	it("does not call a derived name an unknown field, unless its base is not a schema field", () => {
		expect(findProblems(fields)).toEqual([])
		const bad = [f("a"), f("b", { visibleIf: { field: "a.features", contains: "x" } })]
		expect(findProblems(bad)[0]).toMatch(/unknown field 'a.features'/)
	})
})
