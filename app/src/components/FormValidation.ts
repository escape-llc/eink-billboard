import z from "zod"
import type { PropertiesDef } from "./FormDefs"
import { messages } from "./FormMessages"
import { hiddenNames, type ValueSource } from "./FormVisibility"

/** A property as the form holds it: the descriptor plus what the form resolved for it (`list` of a lookup, `children` of a `schema` field). */
export type FormField = PropertiesDef & {
	enum?: string[]
	list?: { value: unknown }[]
	children?: FormField[]
}

// a null/undefined where a value is required reads "Required" rather than zod's type message;
// NaN and the infinities are numbers zod refuses as the wrong type, which the server words as "Must be a finite number"
z.config({
	customError: (issue) => {
		if (issue.code === "invalid_type" && (issue.input === null || issue.input === undefined)) {
			return messages.required
		}
		if (issue.code === "invalid_type" && issue.expected === "array") {
			return messages.list
		}
		if (issue.code === "invalid_type" && issue.expected === "number" && typeof issue.input === "number") {
			return messages.finite
		}
		return undefined
	}
})

// "" and a value the document does not have are both "not set", which is how an optional field is stored (as the server reads a missing one)
const emptyToNull = (val: unknown) => (val === "" || val === undefined ? null : val)

/** Optional fields hold `null` when unset (that is how the server stores them), so null is valid unless the field is required. */
const optionalUnless = (required: boolean, schema: z.ZodTypeAny): z.ZodTypeAny => (required ? schema : z.preprocess(emptyToNull, schema.nullable()))

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
			if (px.format === "date") {
				const iso = z.iso.date({ error: (issue) => (issue.input === null || issue.input === undefined ? messages.required : messages.date) })
				return required ? z.preprocess(emptyToNull, iso) : z.preprocess(emptyToNull, iso.nullable())
			}
			let base: z.ZodTypeAny = z.string()
			if (required) base = (base as z.ZodString).min(1, { error: messages.required })
			// the length and pattern rules apply to a value that is there: "" is unset, which `required` handles
			if (px.minLength !== undefined) base = base.refine((v: unknown) => v === "" || (v as string).length >= px.minLength!, { error: messages.atLeast(px.minLength) })
			if (px.maxLength !== undefined) base = base.refine((v: unknown) => (v as string).length <= px.maxLength!, { error: messages.atMost(px.maxLength) })
			if (px.pattern) {
				const re = new RegExp(px.pattern)
				base = base.refine((v: unknown) => v === "" || re.test(v as string), { error: messages.format })
			}
			if (px.enum && px.enum.length > 0) {
				const allowed = px.enum
				base = base.refine(oneOf(allowed), { error: messages.notAllowed })
			}
			else if (px.list && px.list.length > 0) {
				const allowed = px.list.map(x => x.value)
				base = base.refine(oneOf(allowed), { error: messages.notAllowed })
			}
			return required ? base : z.preprocess(emptyToNull, base.nullable())
		}
		case "boolean":
			return optionalUnless(required, z.boolean())
		case "number":
		case "integer": {
			let base = px.type === "integer" ? z.number().int({ error: messages.wholeNumbers }) : z.number()
			if (px.minimum !== undefined) base = base.min(px.minimum, { error: messages.minimum(px.minimum) })
			if (px.maximum !== undefined) base = base.max(px.maximum, { error: messages.maximum(px.maximum) })
			return optionalUnless(required, base)
		}
		case "array": {
			const key = px.items?.key
			// an item without an optional field has none set (as on the server), so those rules accept a missing key too
			const itemFields = (px.items?.properties ?? []) as FormField[]
			const shape = fieldRules(itemFields)
			for (const f of itemFields) {
				if (shape[f.name] && (f as { required?: boolean }).required !== true) shape[f.name] = shape[f.name]!.optional()
			}
			let list = z.array(z.object(shape))
			if (px.minItems !== undefined) list = list.min(px.minItems, { error: messages.atLeastItems(px.minItems) })
			if (px.maxItems !== undefined) list = list.max(px.maxItems, { error: messages.atMostItems(px.maxItems) })
			const unique = key
				? list.superRefine((items, ctx) => {
					const seen = new Set<unknown>()
					items.forEach((item, index) => {
						const identity = (item as Record<string, unknown>)[key]
						if (typeof identity === "string" && identity !== "") {
							if (seen.has(identity)) ctx.addIssue({ code: "custom", message: messages.unique, path: [index, key] })
							seen.add(identity)
						}
					})
				})
				: list
			return optionalUnless(required, unique)
		}
		case "location": {
			const base = z.object({
				latitude: z.number().min(-90, { error: messages.latitude }).max(90, { error: messages.latitude }),
				longitude: z.number().min(-180, { error: messages.longitude }).max(180, { error: messages.longitude })
			})
			return optionalUnless(required, base)
		}
		case "schema": {
			let base: z.ZodTypeAny = z.string()
			if (required) base = (base as z.ZodString).min(1, { error: messages.required })
			if (px.list && px.list.length > 0) {
				base = base.refine(oneOf(px.list.map(x => x.value)), { error: messages.notAvailable })
			}
			return required ? base : z.preprocess(emptyToNull, base.nullable())
		}
		default: {
			// the server does not check a type it does not know either
			console.warn("no validation for type", px)
			return z.any()
		}
	}
}

/**
 * The rules of every field in the list, children of `schema` fields included, keyed by field name.
 * With `values`, fields hidden by `visibleIf` for those values are left out: a hidden field is not applicable.
 */
export function fieldRules(fields: FormField[], into: Record<string, z.ZodTypeAny> = {}, values?: ValueSource): Record<string, z.ZodTypeAny> {
	const hidden = values ? hiddenNames(fields, values) : new Set<string>()
	const walk = (list: FormField[]) => {
		for (const px of list) {
			const sx = hidden.has(px.name) ? undefined : schemaFor(px)
			if (sx) into[px.name] = sx
			if (px.children) walk(px.children)
		}
	}
	walk(fields)
	return into
}
