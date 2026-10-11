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
	/** of a string: `date` is a `YYYY-MM-DD` day (a date picker), `uri` an address with a scheme and a host, `color` a `#rrggbb` (a color picker) */
	format?: "date" | "uri" | "color"
	/** of a `uri`: the schemes it may use (default http and https) */
	schemes?: string[]
	/** of a string: a check the server runs on the value, behind a Test button (`url` is the route, which gets `{ value }` and answers `{ ok, message }`) */
	test?: { url: string }
	required: boolean
	/** what a new item starts with (null or absent: nothing) */
	default?: unknown
	/** shown under the field as help text */
	description?: string
	/** a button that opens a page of someone else's in a new tab (where to get an API key); an `https` address only */
	link?: { url: string, label: string }
	/** a predicate over the other fields' values: hidden (not validated, saved as null) when false; see FormVisibility.ts */
	visibleIf?: Predicate
	/** shown as a password input; the server never sends the stored value back */
	writeOnly?: boolean
	lookup?: string
	/** the allowed values of a string field */
	enum?: string[]
	minimum?: number
	maximum?: number
	/**
	 * of an array: how many items, and what each is. A list of objects (`type: "object"`, flat fields; `key` names the field that identifies a row
	 * and must be unique); or a multi-select (`type: "string"`), the values chosen from the field's `lookup` or from `items.enum`
	 */
	minItems?: number
	maxItems?: number
	items?: { type: "object", key?: string, properties: FieldDef[], action?: RowActionDef } | { type: "string", enum?: string[] }
	minLength?: number
	maxLength?: number
	/** a regular expression both JavaScript and Python read the same way */
	pattern?: string
	step?: number
	minFractionDigits?: number
	maxFractionDigits?: number
}
/**
 * A button on each row of a list, which runs a few steps against our own route for the *saved* row (found by its key), such as signing in an account:
 * `POST {url}/start { key }` answers what to show (`message`, `link`, `code`, `input`, `poll` seconds) and a `session`; then `{url}/continue { session, value }`
 * (with what was typed in `input`) or `{url}/poll { session }` until the answer is `done`, with `ok` and a `message`.
 */
export type RowActionDef = {
	url: string
	label: string
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
