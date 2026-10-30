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
	/** of a string: `date` is a `YYYY-MM-DD` day (a date picker), `uri` an address with a scheme and a host, `color` a `#rrggbb` (a color picker), `multiline` a text area */
	format?: "date" | "uri" | "color" | "multiline"
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
	/** how the field is laid out: `api-key` is a service's key (write-only, required, a Test and a link; test_api_keys.py) */
	widget?: "api-key"
	lookup?: string
	/** the allowed values of a string field */
	enum?: string[]
	minimum?: number
	maximum?: number
	/**
	 * of an array: how many items, and what each is. A list of objects (`type: "object"`, flat fields; `key` names the field that identifies a row
	 * and must be unique, a whole number as well as text; `once` names a field and the values of it that only one row may have; `plugin`: a row of a certain value carries a plugin's
	 * settings); or a multi-select (`type: "string"`), the values chosen from the field's `lookup` or from `items.enum`
	 */
	minItems?: number
	maxItems?: number
	items?: { type: "object", key?: string, once?: { field: string, values: string[] }, plugin?: RowPluginDef, properties: FieldDef[], action?: RowActionDef } | { type: "string", enum?: string[] }
	minLength?: number
	maxLength?: number
	/** a regular expression both JavaScript and Python read the same way */
	pattern?: string
	/** `format: "multiline"`: the lines a text area shows before it grows */
	rows?: number
	/**
	 * The fields a text may use (`{name}` in it), each with what it stands for: shown under the field, and the only names the text may hold.
	 * The data that supplies the values lists them (a data source's `tokens`), so a name is never a guess.
	 */
	tokens?: { name: string, description: string }[]
	/** the capabilities whose contracts supply `tokens` (copied in when the descriptors are read, so the form sees `tokens`) */
	tokensFrom?: string[]
	/** of a number: what it is counted in (`hours`, `MB`), shown in the input's group, after the number */
	units?: string
	step?: number
	minFractionDigits?: number
	maxFractionDigits?: number
}
/**
 * A button on each row of a list, which runs a few steps against our own route for the *saved* row (found by its key), such as signing in an account:
 * `POST {url}/start { key }` answers what to show (`message`, `link`, `code`, `input`, `poll` seconds) and a `session`; then `{url}/continue { session, value }`
 * (with what was typed in `input`) or `{url}/poll { session }` until the answer is `done`, with `ok` and a `message`.
 */
/**
 * Rows of a list that carry the settings of a plugin (a button of the device that runs a Priority Update): the plugin's id, the row's field that holds them (an object, not shown as a column),
 * and `when`, the row's field and value that make a row carry them. `run` is the address (a list of ours, then `/<key>/run`) that runs a saved row, for a Run now button.
 */
export type RowPluginDef = { id: string, field: string, when: { field: string, const: string }, run?: string }
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
	/** fields whose values go as query parameters (the form's, or in a list row the row's): the list is fetched again when one changes, and waits while one is empty */
	with?: string[]
	/**
	 * the field gets a search box: what is typed goes as `q`, on Enter or Search (never per keystroke). Before a search only a stored value is asked
	 * for (as `q`: the route finds an entry by its own value too), so it shows its name. Not in a row
	 */
	search?: boolean
}
export type LookupSettings = {
	/** the array property of the declaring plugin's or data source's own settings that holds the choices */
	settings: string
	/** the item field that is the value (default `name`) and the one shown (default the value) */
	value?: string
	label?: string
	/** the data source (an id, or a capability `data-*`: the device's provider of it) whose settings hold the list, instead of the declaring one */
	from?: string
}
export type LookupValue = {
	name: string;
	value: unknown;
	/** a choice that is listed and cannot be chosen (a pin the panel uses); its name says why */
	disabled?: boolean;
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
	default: Record<string, unknown> | null
}

/** Whose own settings a form's `settings` lookups choose from (a plugin's instance form: that plugin). */
export type Owner = { kind: "plugin" | "datasource" | "display", id: string }
/** What the app is told of an installed plugin, data source or display (`GET /api/plugins`, ...): what a `schema` lookup offers. */
export type Descriptor = {
	id: string
	name: string
	features?: string[]
	instanceSettings?: FormDef
	uses?: string[]
	requires?: string[]
	keepsList?: boolean
}
/** One choice of a `schema` lookup: a plugin, data source or display, with the form of its own settings (the fields it brings). */
export type SchemaChoice = LookupValue & {
	value: string
	schema?: FormDef
	owner: Owner
	uses?: string[]
	requires?: string[]
	features?: string[]
	keepsList?: boolean
}
/** Where a resolved field's choices came from: fixed `items`, a `url` (or a `settings` list, served by a route), or the installed `schema`s. */
export type ListType = "items" | "url" | "schema"
/** What the form adds to a field of the descriptor when it builds it (BasicForm's `formProperties`). */
type Resolved = {
	/** the choices of a `lookup` (a `schema` field's are `SchemaChoice`s) */
	list?: (LookupValue | SchemaChoice)[]
	listType?: ListType
	/** the route a `url` or `settings` lookup is read from (null: none, as for a `settings` lookup with no owner) */
	lookupUrl?: string | null
	/** why the list could not be loaded, shown under the field (never a choice) */
	lookupError?: string
	/** a `url` lookup's list has been answered (or failed): an empty list is then really empty */
	lookupReady?: boolean
	/** a `url` lookup's `with` and `search`: the field fetches its list itself, for the values it needs (LookupQuery.ts) */
	lookupWith?: string[]
	lookupSearch?: boolean
	/** a `schema` field's: the fields of the chosen source */
	children?: ResolvedField[]
	/** a `schema` field's: the data sources the chosen one uses that the device lacks, and the capabilities no provider supplies */
	usesMissing?: string[]
	providersMissing?: string[]
}
/** A field as the form shows it: the descriptor's definition and what the form resolved for it; a list's row fields are resolved too. */
export type ResolvedFieldDef = Omit<FieldDef, "items"> & Resolved & {
	items?: { type: "object", key?: string, once?: { field: string, values: string[] }, plugin?: RowPluginDef, properties: ResolvedFieldDef[], action?: RowActionDef } | { type: "string", enum?: string[] }
}
export type ResolvedField = ResolvedFieldDef | (FieldGroupDef & Resolved)
/** The values of a form, by field name. */
export type FormValues = Record<string, unknown>
