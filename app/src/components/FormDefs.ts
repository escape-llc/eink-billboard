export type FieldGroupDef = {
	name: string
	label: string
	type: "header"
}
export type FieldDef = {
	name: string
	label: string
	type: "string" | "boolean" | "number" | "int" | "location" | "schema" | "date"
	required: boolean
	lookup?: string
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
