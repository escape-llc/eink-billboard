import { describe, expect, it } from "vitest"
import { z } from "zod"
import { fieldRules, schemaFor, type FormField } from "./FormValidation"
import rules from "../../../python/tests/form_rules.json"

const field = (over: Record<string, unknown>) => ({ name: "f", label: "F", required: true, ...over }) as FormField
const check = (px: FormField, value: unknown) => {
	const sx = schemaFor(px)!
	const r = sx.safeParse(value)
	return r.success ? null : r.error.issues[0]!.message
}

describe("string", () => {
	it("required rejects empty and null with 'Required'", () => {
		const px = field({ type: "string" })
		expect(check(px, "")).toBe("Required")
		expect(check(px, null)).toBe("Required")
		expect(check(px, "x")).toBeNull()
	})
	it("optional accepts empty and null", () => {
		const px = field({ type: "string", required: false })
		expect(check(px, "")).toBeNull()
		expect(check(px, null)).toBeNull()
	})
	it("enum limits the values, optional or not", () => {
		const px = field({ type: "string", enum: ["a", "b"] })
		expect(check(px, "a")).toBeNull()
		expect(check(px, "z")).toBe("Not one of the allowed values")
		expect(check(field({ type: "string", enum: ["a"], required: false }), null)).toBeNull()
	})
	it("a lookup list limits the values once it is loaded, and is ignored while empty", () => {
		expect(check(field({ type: "string", list: [{ value: "x" }] }), "y")).toBe("Not one of the allowed values")
		expect(check(field({ type: "string", list: [{ value: "x" }] }), "x")).toBeNull()
		expect(check(field({ type: "string", list: [] }), "anything")).toBeNull()
	})
})

describe("number and int", () => {
	it("min and max of zero are enforced (they used to be ignored)", () => {
		expect(check(field({ type: "number", min: 0 }), -1)).toBe("Minimum 0")
		expect(check(field({ type: "number", min: 0 }), 0)).toBeNull()
		expect(check(field({ type: "number", max: 0 }), 1)).toBe("Maximum 0")
	})
	it("required rejects null, optional accepts it", () => {
		expect(check(field({ type: "number" }), null)).toBe("Required")
		expect(check(field({ type: "number", required: false }), null)).toBeNull()
	})
	it("int rejects fractions", () => {
		expect(check(field({ type: "int" }), 1.5)).toBe("Whole numbers only")
		expect(check(field({ type: "int", min: 1 }), 0)).toBe("Minimum 1")
		expect(check(field({ type: "int" }), 3)).toBeNull()
	})
})

describe("location", () => {
	it("optional accepts null (the factory default), required does not", () => {
		expect(check(field({ type: "location", required: false }), null)).toBeNull()
		expect(check(field({ type: "location" }), null)).toBe("Required")
	})
	it("checks the ranges", () => {
		const px = field({ type: "location" })
		expect(check(px, { latitude: 45, longitude: -122 })).toBeNull()
		expect(check(px, { latitude: 91, longitude: 0 })).toBe("Latitude is -90 to 90")
		expect(check(px, { latitude: 0, longitude: -181 })).toBe("Longitude is -180 to 180")
	})
})

describe("schema and date", () => {
	it("a schema field must be one of the available choices", () => {
		const px = field({ type: "schema", list: [{ value: "image-folder" }] })
		expect(check(px, "image-folder")).toBeNull()
		expect(check(px, "nope")).toBe("Not one of the available choices")
		expect(check(px, "")).toBe("Required")
	})
	it("dates are YYYY-MM-DD", () => {
		expect(check(field({ type: "date" }), "2026-10-05")).toBeNull()
		expect(check(field({ type: "date" }), "2026-02-31")).not.toBeNull()
		expect(check(field({ type: "date", required: false }), "")).toBeNull()
	})
})

describe("fieldRules", () => {
	it("skips headers and includes the children of schema fields", () => {
		const rules = fieldRules([
			{ name: "h", label: "H", type: "header" },
			field({ name: "dataSource", type: "schema", children: [field({ name: "folder", type: "string" })] })
		] as FormField[])
		expect(Object.keys(rules).sort()).toEqual(["dataSource", "folder"])
	})
})

// the cases the server's validate_properties is tested against too (python/tests/test_web_api.py)
// JSON cannot hold NaN or Infinity, so the file writes them as { "$number": "NaN" }
const decode = (v: unknown): unknown =>
	v !== null && typeof v === "object" && "$number" in v ? Number((v as { $number: string }).$number) : v

describe("what a form submits", () => {
	// BasicForm submits `z.object(fieldRules(...)).safeParse(values).data`: only the fields of the selection come out
	const slideShow = [field({ name: "slideMax", type: "int" }), field({ name: "slideMinutes", type: "int" })]
	const interstitial = [field({ name: "slideMinutes", type: "int" })]
	const submit = (fields: FormField[], values: Record<string, unknown>) => {
		const r = z.object(fieldRules(fields, {}, values)).safeParse(values)
		return r.success ? r.data : null
	}
	it("leaves out values left over from a previous selection or that the descriptor does not know", () => {
		const values = { slideMax: 4, slideMinutes: 2, strayFromOldPlugin: "x" }
		expect(submit(slideShow, values)).toEqual({ slideMax: 4, slideMinutes: 2 })
		expect(submit(interstitial, values)).toEqual({ slideMinutes: 2 })
	})
	it("leaves out a hidden field (the form then saves it as null)", () => {
		const fields = [field({ name: "on", type: "boolean" }), field({ name: "detail", type: "string", visibleIf: { field: "on", eq: true } })]
		expect(submit(fields, { on: false, detail: "kept?" })).toEqual({ on: false })
	})
})

describe("shared rules (form_rules.json)", () => {
	for (const c of rules.cases) {
		it(c.name, () => {
			expect(check(c.field as unknown as FormField, decode(c.value))).toBe(c.error)
		})
	}
})
