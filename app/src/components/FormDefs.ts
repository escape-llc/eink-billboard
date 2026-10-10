import type { Predicate } from "./FormVisibility"

export type FieldGroupDef = {
	name: string
	title: string
	type: "header"
	description?: string
	visibleIf?: Predicate
}
export type FieldDef = {
	name: string
	title: string
	type: "string" | "boolean" | "number" | "integer" | "location" | "schema" | "array"
	/** of a string: `date` is a `YYYY-MM-DD` day (a date picker) */
	format?: "date"
	required: boolean
	/** what a new item starts with (null or absent: nothing) */
	default?: unknown
	/** shown under the field as help text */
	description?: string
	/** a predicate over the other fields' values: hidden (not validated, saved as null) when false; see FormVisibility.ts */
	visibleIf?: Predicate
	/** shown as a password input; the server never sends the stored value back */
	writeOnly?: boolean
	lookup?: string
	/** the allowed values of a string field */
	enum?: string[]
	minimum?: number
	maximum?: number
	/** of an array: how many items, and the object each is (flat fields only); `key` names the field that identifies an item and must be unique */
	minItems?: number
	maxItems?: number
	items?: { type: "object", key?: string, properties: FieldDef[] }
	minLength?: number
	maxLength?: number
	/** a regular expression both JavaScript and Python read the same way */
	pattern?: string
	step?: number
	minFractionDigits?: number
	maxFractionDigits?: number
}
export type LookupSchema = {
	schema: string
	features?: string[]
}
export type LookupUrl = {
	url: string
}
export type LookupSettings = {
	/** the array property of the declaring plugin's or data source's own settings that holds the choices */
	settings: string
	/** the item field that is the value (default `name`) and the one shown (default the value) */
	value?: string
	label?: string
}
export type LookupValue = {
	name: string;
	value: unknown;
}
export type LookupItems = {
	items: LookupValue[]
}
export type LookupDef = LookupItems | LookupUrl | LookupSchema | LookupSettings
export type PropertiesDef = FieldDef | FieldGroupDef
export type SchemaType = {
	lookups: Record<string,LookupDef>
	properties: PropertiesDef[]
}
export type FormDef = {
	schema: SchemaType
	default: Record<string,any>
}
