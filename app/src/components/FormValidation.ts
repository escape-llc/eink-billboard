import z from "zod"
import type { FieldDef, ResolvedField } from "./FormDefs"
import { messages } from "./FormMessages"
import { hiddenNames, type ValueSource } from "./FormVisibility"
import { unknownToken } from "./PromptTokens"

/** A property as the form holds it: the descriptor plus what the form resolved for it (`list` of a lookup, `children` of a `schema` field). */
export type FormField = ResolvedField

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
// `format: "uri"`: the same expression as `_URI` in python/web/documents.py
const URI = /^([A-Za-z][A-Za-z0-9+.-]*):\/\/([^/?#\s]+)(\S*)$/
const DEFAULT_SCHEMES = ["http", "https"]
export const isUri = (value: string, schemes: readonly string[] = DEFAULT_SCHEMES): boolean => {
	const found = URI.exec(value)
	return found !== null && schemes.includes(found[1]!.toLowerCase())
}

// `format: "color"`: the same expression as `_COLOR` in python/web/documents.py
const COLOR = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/
/** What the server sends for a stored write-only value (SECRET_MASK in python/web/documents.py). */
export const SECRET_MASK = "********"

const emptyToNull = (val: unknown) => (val === "" || val === undefined ? null : val)

/** Optional fields hold `null` when unset (that is how the server stores them), so null is valid unless the field is required. */
const optionalUnless = (required: boolean, schema: z.ZodTypeAny): z.ZodTypeAny => (required ? schema : z.preprocess(emptyToNull, schema.nullable()))

/** Only checks membership when the list is known (URL lookups load later, so an empty list means "not loaded yet"). */
function oneOf(values: readonly unknown[]) {
	return (val: unknown) => val === null || val === undefined || val === "" || values.length === 0 || values.includes(val)
}

/** The rules for one field, or `undefined` when it holds no value (a header). The same rules are written down in docs/forms-and-descriptors.md and checked again by the server. */
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
			// a write-only field shows the mask for the stored value: the rules below are the stored value's, checked by the server once it is restored
			const masked = (v: unknown) => px.writeOnly === true && v === SECRET_MASK
			// the length and pattern rules apply to a value that is there: "" is unset, which `required` handles
			if (px.minLength !== undefined) base = base.refine((v: unknown) => v === "" || masked(v) || (v as string).length >= px.minLength!, { error: messages.atLeast(px.minLength) })
			if (px.maxLength !== undefined) base = base.refine((v: unknown) => masked(v) || (v as string).length <= px.maxLength!, { error: messages.atMost(px.maxLength) })
			if (px.format === "uri") {
				const schemes = px.schemes
				base = base.refine((v: unknown) => v === "" || isUri(v as string, schemes), { error: messages.url })
			}
			if (px.format === "color") {
				base = base.refine((v: unknown) => v === "" || COLOR.test(v as string), { error: messages.color })
			}
			if (px.tokens) {
				// the fields a text may use are the property's own list: any other `{name}` is refused now, not left as a hole at run time
				const known = px.tokens.map(t => t.name)
				base = base.superRefine((v: unknown, ctx) => {
					const unknown = typeof v === "string" ? unknownToken(v, known) : undefined
					if (unknown !== undefined) ctx.addIssue({ code: "custom", message: messages.unknownField(unknown) })
				})
			}
			if (px.pattern) {
				const re = new RegExp(px.pattern)
				base = base.refine((v: unknown) => v === "" || masked(v) || re.test(v as string), { error: messages.format })
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
			if (px.items?.type === "string") {
				// a multi-select: each value one of the choices (`items.enum`, or the lookup's list once it is loaded)
				const choice = schemaFor({ name: px.name, title: px.title, type: "string", required: true, enum: px.items.enum, list: px.list } as FormField)!
				let chosen = z.array(choice)
				if (px.minItems !== undefined) chosen = chosen.min(px.minItems, { error: messages.atLeastItems(px.minItems) })
				if (px.maxItems !== undefined) chosen = chosen.max(px.maxItems, { error: messages.atMostItems(px.maxItems) })
				return optionalUnless(required, chosen)
			}
			const items = px.items as { key?: string, once?: { field: string, values: string[] }, plugin?: { field: string, when: { field: string, const: string } }, properties?: FieldDef[] } | undefined
			const key = items?.key
			const once = items?.once
			const carries = (row: Record<string, unknown>) => items?.plugin !== undefined && row[items.plugin.when.field] === items.plugin.when.const
			const itemFields = (items?.properties ?? []) as FormField[]
			// each row has its own rules: a row's `visibleIf` reads the fields of that row, and a hidden field is not checked (and is saved as null)
			let list = z.array(z.record(z.string(), z.unknown(), { error: messages.object }))
			if (px.minItems !== undefined) list = list.min(px.minItems, { error: messages.atLeastItems(px.minItems) })
			if (px.maxItems !== undefined) list = list.max(px.maxItems, { error: messages.atMostItems(px.maxItems) })
			const rows = list
				.superRefine((rows, ctx) => {
					const seen = new Set<unknown>()
					const seenOnce = new Set<unknown>()
					rows.forEach((row, index) => {
						const r = rowRules(itemFields, row).safeParse(row)
						if (!r.success) {
							for (const issue of r.error.issues) ctx.addIssue({ code: "custom", message: issue.message, path: [index, ...issue.path] })
						}
						const identity = key ? row[key] : undefined
						if (key && ((typeof identity === "string" && identity !== "") || (typeof identity === "number" && Number.isInteger(identity)))) {
							if (seen.has(identity)) ctx.addIssue({ code: "custom", message: messages.unique, path: [index, key] })
							seen.add(identity)
						}
						// a row that carries a plugin's settings has them (they are checked by the dialog that sets them, and by the server)
						if (items?.plugin && carries(row) && (typeof row[items.plugin.field] !== "object" || row[items.plugin.field] === null)) {
							ctx.addIssue({ code: "custom", message: messages.required, path: [index, items.plugin.field] })
						}
						// a value that only one row may have (the device's Play, Stop, Toggle and Next: each belongs to one button)
						const chosen = once ? row[once.field] : undefined
						if (once && typeof chosen === "string" && once.values.includes(chosen)) {
							if (seenOnce.has(chosen)) ctx.addIssue({ code: "custom", message: messages.alreadyUsed, path: [index, once.field] })
							seenOnce.add(chosen)
						}
					})
				})
				.transform(rows => rows.map(row => {
					const r = rowRules(itemFields, row).safeParse(row)
					// what the row's fields do not declare is kept (a row's plugin settings), except where the row does not carry it
					const out: Record<string, unknown> = { ...row, ...(r.success ? r.data as Record<string, unknown> : {}) }
					if (items?.plugin && !carries(row)) delete out[items.plugin.field]
					// plain data: the form's values are reactive, and what the rules hand on is copied when it is saved
					else if (items?.plugin) out[items.plugin.field] = JSON.parse(JSON.stringify(row[items.plugin.field] ?? null))
					hiddenNames(itemFields, row).forEach(name => { out[name] = null })
					return out
				}))
			return optionalUnless(required, rows)
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

/** The rules of one row of a list of objects: an item without an optional field has none set (as on the server), so those rules accept a missing key too. */
function rowRules(itemFields: FormField[], row: Record<string, unknown>): z.ZodObject {
	const shape = fieldRules(itemFields, {}, row)
	for (const f of itemFields) {
		if (shape[f.name] && (f as { required?: boolean }).required !== true) shape[f.name] = shape[f.name]!.optional()
	}
	return z.object(shape)
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
