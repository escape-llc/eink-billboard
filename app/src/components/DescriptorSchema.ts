import { z } from "zod"
import type { FieldDef, FieldGroupDef, LookupDef, SchemaType } from "./FormDefs"
import type { Predicate } from "./FormVisibility"

/**
 * The shape of a descriptor's settings section (`settings`, `instanceSettings`, an NVE schema file) as the form reads it.
 * Every object is strict: a key the form does not know (a misspelled `minLenght`, a `requried`) is an error, since the form and the server
 * would silently ignore it and its rule would not apply. What a value means (a default passing its own rules, a `visibleIf` naming a field)
 * is checked by the Python tests (`test_web_api`, `test_item_audit`), not here.
 */

const predicate = z.custom<Predicate>(v => typeof v === "object" && v !== null && !Array.isArray(v), "a visibleIf is an object")

/** What a row field and a field share; a row's fields are flat (no list in a row). */
const scalarField = {
	name: z.string().min(1),
	title: z.string(),
	required: z.boolean(),
	default: z.unknown().optional(),
	description: z.string().optional(),
	visibleIf: predicate.optional(),
	format: z.enum(["date", "uri", "color", "multiline"]).optional(),
	schemes: z.array(z.string()).optional(),
	test: z.strictObject({ url: z.string() }).optional(),
	link: z.strictObject({ url: z.string(), label: z.string() }).optional(),
	writeOnly: z.boolean().optional(),
	widget: z.enum(["api-key"]).optional(),
	lookup: z.string().optional(),
	enum: z.array(z.string()).optional(),
	minimum: z.number().optional(),
	maximum: z.number().optional(),
	minLength: z.number().int().optional(),
	maxLength: z.number().int().optional(),
	pattern: z.string().optional(),
	rows: z.number().int().optional(),
	tokens: z.array(z.strictObject({ name: z.string(), description: z.string() })).optional(),
	tokensFrom: z.array(z.string()).optional(),
	step: z.number().optional(),
	minFractionDigits: z.number().int().optional(),
	maxFractionDigits: z.number().int().optional(),
}

export const rowFieldSchema = z.strictObject({
	...scalarField,
	type: z.enum(["string", "boolean", "number", "integer", "location"]),
})

const itemsSchema = z.discriminatedUnion("type", [
	z.strictObject({
		type: z.literal("object"),
		key: z.string().optional(),
		once: z.strictObject({ field: z.string(), values: z.array(z.string()) }).optional(),
		plugin: z.strictObject({ id: z.string(), field: z.string(), when: z.strictObject({ field: z.string(), const: z.string() }), run: z.string().optional() }).optional(),
		properties: z.array(rowFieldSchema),
		action: z.strictObject({ url: z.string(), label: z.string() }).optional(),
	}),
	z.strictObject({ type: z.literal("string"), enum: z.array(z.string()).optional() }),
])

export const fieldSchema = z.strictObject({
	...scalarField,
	type: z.enum(["string", "boolean", "number", "integer", "location", "schema", "array"]),
	minItems: z.number().int().optional(),
	maxItems: z.number().int().optional(),
	items: itemsSchema.optional(),
})

export const groupSchema = z.strictObject({
	name: z.string().min(1),
	title: z.string(),
	type: z.literal("header"),
	description: z.string().optional(),
	visibleIf: predicate.optional(),
})

export const propertySchema = z.discriminatedUnion("type", [groupSchema, fieldSchema])

/** The four kinds of lookup; an object that is none of them is an error. */
export const lookupSchema = z.union([
	z.strictObject({ items: z.array(z.strictObject({ name: z.string(), value: z.unknown() })) }),
	z.strictObject({ url: z.string(), with: z.array(z.string()).min(1).optional(), search: z.boolean().optional() }),
	z.strictObject({ schema: z.string(), features: z.array(z.string()).optional() }),
	z.strictObject({ settings: z.string(), value: z.string().optional(), label: z.string().optional(), from: z.string().optional() }),
])

export const schemaSchema = z.strictObject({
	lookups: z.record(z.string(), lookupSchema).optional(),
	properties: z.array(propertySchema),
})

/** A settings section: the schema, and for a descriptor's own settings (and an NVE file) its version and default document (null: it has no settings). */
export const sectionSchema = z.strictObject({
	_schema: z.string().optional(),
	schema: schemaSchema,
	default: z.record(z.string(), z.unknown()).nullable().optional(),
})

// What the schema accepts is what FormDefs.ts declares: a type the form reads cannot drift from the descriptors without failing the type-check.
type Agrees<T extends true> = T
type Accepted<T extends z.ZodType> = z.infer<T>
export type FieldsAgree = Agrees<Accepted<typeof fieldSchema> extends FieldDef ? true : false>
export type GroupsAgree = Agrees<Accepted<typeof groupSchema> extends FieldGroupDef ? true : false>
export type LookupsAgree = Agrees<Accepted<typeof lookupSchema> extends LookupDef ? true : false>
export type SchemasAgree = Agrees<Omit<Accepted<typeof schemaSchema>, "lookups"> & { lookups: Record<string, LookupDef> } extends SchemaType ? true : false>
// and the other way: every key FormDefs.ts declares is one the schema knows
export type NoFieldKeyForgotten = Agrees<[Exclude<keyof FieldDef, keyof Accepted<typeof fieldSchema>>] extends [never] ? true : false>

/** Every problem with one settings section, each as `where/path: message`; none: it is a section the form can read. */
export function sectionProblems(section: unknown, where: string): string[] {
	const parsed = sectionSchema.safeParse(section)
	if (!parsed.success) {
		return parsed.error.issues.map(issue => `${[where, ...issue.path].join("/")}: ${issue.message}`)
	}
	// a lookup a field names is one its schema defines (a row's fields included), or the form offers nothing
	const lookups = parsed.data.schema.lookups ?? {}
	const problems: string[] = []
	// a lookup's `with` names fields where it is used: the schema's own fields, or in a row that row's; a row has no search box
	const formNames = parsed.data.schema.properties.map(px => px.name)
	parsed.data.schema.properties.forEach((px, ix) => {
		if (px.type === "header") return
		const fields: [string, { lookup?: string }, string[] | null][] = [[`${ix}`, px, formNames]]
		if (px.items?.type === "object") {
			const rowNames = px.items.properties.map(rx => rx.name)
			px.items.properties.forEach((rx, rix) => fields.push([`${ix}/items/properties/${rix}`, rx, rowNames]))
		}
		for (const [at, fx, names] of fields) {
			if (fx.lookup === undefined) continue
			const lookup = lookups[fx.lookup]
			if (lookup === undefined) {
				problems.push(`${where}/schema/properties/${at}/lookup: "${fx.lookup}" is not one of the schema's lookups`)
				continue
			}
			if (!("url" in lookup)) continue
			for (const name of lookup.with ?? []) {
				if (!names?.includes(name) || name === (fx as { name?: string }).name) problems.push(`${where}/schema/properties/${at}/lookup: "${fx.lookup}" is sent with "${name}", which is not another field ${at.includes("/items/") ? "of the row" : "of the schema"}`)
			}
			if (lookup.search && at.includes("/items/")) problems.push(`${where}/schema/properties/${at}/lookup: "${fx.lookup}" is a search, which a list row cannot have`)
		}
	})
	return problems
}
