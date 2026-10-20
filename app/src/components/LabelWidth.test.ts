import { describe, expect, it } from "vitest"
import { adaptiveLabelWidth, labelsOf } from "./LabelWidth"

describe("the label column", () => {
	it("is never narrower than the usual width, whatever the labels", () => {
		expect(adaptiveLabelWidth([])).toBe("10rem")
		expect(adaptiveLabelWidth(["Name", "Id"])).toBe("10rem")
	})
	it("grows to the longest label, in half rems", () => {
		// 24 characters: 24 * 0.6 + 2 = 16.4, up to 16.5
		expect(adaptiveLabelWidth(["Keep Downloads (hours)", "Downloads Pool Size (MB)"])).toBe("16.5rem")
	})
	it("stops at the ceiling, where a very long label wraps", () => {
		expect(adaptiveLabelWidth(["x".repeat(200)])).toBe("24rem")
	})
	it("reads the labels of the fields and of the fields their choices bring, and not a header", () => {
		const fields = [
			{ title: "Source", type: "schema", children: [{ title: "Forget Unused Downloads After (days)", type: "integer" }] },
			{ title: "Section", type: "header" },
			{ type: "string" },
		]
		expect(labelsOf(fields)).toEqual(["Source", "Forget Unused Downloads After (days)"])
		expect(labelsOf(undefined)).toEqual([])
	})
})
