import { describe, expect, it } from "vitest"
import { evaluate, findProblems, hiddenNames } from "./FormVisibility"
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
		expect(findProblems([f("b", { visibleIf: { field: "b" } })]).join()).toMatch(/needs const, enum or set/)
		expect(findProblems([f("a", { visibleIf: { field: "b", set: true } }), f("b", { visibleIf: { field: "a", set: true } })]).join()).toMatch(/cycle: a -> b -> a|cycle: b -> a -> b/)
	})
})
