import z from "zod"
import type { PropertiesDef } from "./FormDefs"

/** A property as the form holds it: the descriptor plus what the form resolved for it (`list` of a lookup, `children` of a `schema` field). */
export type FormField = PropertiesDef & {
	enum?: string[]
	list?: { value: unknown }[]
	children?: FormField[]
}

// a null/undefined where a value is required reads "Required" rather than zod's type message
z.config({
	customError: (issue) => {
		if (issue.code === "invalid_type" && (issue.input === null || issue.input === undefined)) {
			return "Required"
		}
		return undefined
	}
})

const emptyToNull = (val: unknown) => (val === "" ? null : val)

/** Optional fields hold `null` when unset (that is how the server stores them), so null is valid unless the field is required. */
const optionalUnless = (required: boolean, schema: z.ZodTypeAny): z.ZodTypeAny => (required ? schema : schema.nullable())

/** Only checks membership when the list is known (URL lookups load later, so an empty list means "not loaded yet"). */
function oneOf(values: readonly unknown[]) {
	return (val: unknown) => val === null || val === undefined || val === "" || values.length === 0 || values.includes(val)
}

/** The rules for one field, or `undefined` when it holds no value (a header). The same rules are written down in AGENTS.md and checked again by the server. */
export function schemaFor(px: FormField): z.ZodTypeAny | undefined {
	if (!px) return undefined
	if (px.type === "header") return undefined
	const required = px.required === true
	switch (px.type) {
		case "string": {
			let base: z.ZodTypeAny = z.string()
			if (required) base = (base as z.ZodString).min(1, { error: "Required" })
			if (px.enum && px.enum.length > 0) {
				const allowed = px.enum
				base = base.refine(oneOf(allowed), { error: "Not one of the allowed values" })
			}
			else if (px.list && px.list.length > 0) {
				const allowed = px.list.map(x => x.value)
				base = base.refine(oneOf(allowed), { error: "Not one of the allowed values" })
			}
			return required ? base : z.preprocess(emptyToNull, base.nullable())
		}
		case "boolean":
			return z.boolean()
		case "number":
		case "int": {
			let base = px.type === "int" ? z.number().int({ error: "Whole numbers only" }) : z.number()
			if (px.min !== undefined) base = base.min(px.min, { error: `Minimum ${px.min}` })
			if (px.max !== undefined) base = base.max(px.max, { error: `Maximum ${px.max}` })
			return optionalUnless(required, base)
		}
		case "location": {
			const base = z.object({
				latitude: z.number().min(-90, { error: "Latitude is -90 to 90" }).max(90, { error: "Latitude is -90 to 90" }),
				longitude: z.number().min(-180, { error: "Longitude is -180 to 180" }).max(180, { error: "Longitude is -180 to 180" })
			})
			return optionalUnless(required, base)
		}
		case "schema": {
			let base: z.ZodTypeAny = z.string()
			if (required) base = (base as z.ZodString).min(1, { error: "Required" })
			if (px.list && px.list.length > 0) {
				base = base.refine(oneOf(px.list.map(x => x.value)), { error: "Not one of the available choices" })
			}
			return required ? base : z.preprocess(emptyToNull, base.nullable())
		}
		case "date": {
			const iso = z.iso.date({ error: (issue) => (issue.input === null || issue.input === undefined ? "Required" : "Expected a date (YYYY-MM-DD)") })
			return required ? z.preprocess(emptyToNull, iso) : z.preprocess(emptyToNull, iso.nullable())
		}
		default: {
			console.warn("no validation for type, using 'string'", px)
			const base = z.string()
			return (px as { required?: boolean }).required === true ? base.min(1, { error: "Required" }) : base
		}
	}
}

/** The rules of every field in the list, children of `schema` fields included, keyed by field name. */
export function fieldRules(fields: FormField[], into: Record<string, z.ZodTypeAny> = {}): Record<string, z.ZodTypeAny> {
	for (const px of fields) {
		const sx = schemaFor(px)
		if (sx) into[px.name] = sx
		if (px.children) fieldRules(px.children, into)
	}
	return into
}
