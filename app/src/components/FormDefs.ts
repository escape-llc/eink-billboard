import type { Predicate } from "./FormVisibility"

export type FieldGroupDef = {
	name: string
	label: string
	type: "header"
	description?: string
	visibleIf?: Predicate
}
export type FieldDef = {
	name: string
	label: string
	type: "string" | "boolean" | "number" | "int" | "location" | "schema" | "date"
	required: boolean
	/** what a new item starts with (null or absent: nothing) */
	default?: unknown
	/** shown under the field as help text */
	description?: string
	/** a predicate over the other fields' values: hidden (not validated, saved as null) when false; see FormVisibility.ts */
	visibleIf?: Predicate
	/** shown as a password input; the server never sends the stored value back */
	secret?: boolean
	lookup?: string
	/** the allowed values of a string field */
	enum?: string[]
	min?: number
	max?: number
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
export type LookupValue = {
	name: string;
	value: unknown;
}
export type LookupItems = {
	items: LookupValue[]
}
export type LookupDef = LookupItems | LookupUrl | LookupSchema
export type PropertiesDef = FieldDef | FieldGroupDef
export type SchemaType = {
	lookups: Record<string,LookupDef>
	properties: PropertiesDef[]
}
export type FormDef = {
	schema: SchemaType
	default: Record<string,any>
}
