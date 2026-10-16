/**
 * Conditional visibility: a property may carry `visibleIf`, a small JSON predicate over the other fields' values.
 * The server applies the same rules (`python/web/visibility.py`); the cases both must pass are in `python/tests/form_visibility.json`.
 *
 *   { "field": "randomizeDate", "const": false }    const | enum | set (true: has a value, false: has none) | contains (a list value holds it)
 *   { "all": [ ... ] }  { "any": [ ... ] }  { "not": { ... } }
 *
 * Names are the form's field names (children of a `schema` field share the same namespace). An unset value (undefined, null, "")
 * reads as `null`. A field that is hidden is not applicable: it is not validated and is saved as `null`.
 *
 * A `schema` field (a plugin's data source) also has values derived from the source it chose, which a predicate may read: `<field>.features` (its
 * `features`, a list: `contains`) and `<field>.keepsList` (true when its list outlasts a visit). So a setting that only means something for one kind of
 * source (the Slide Show's list settings) is shown only when the chosen source is that kind. The server derives the same values.
 */
import type { FormField } from "./FormValidation"

export type Predicate =
	| { field: string, const?: unknown, enum?: unknown[], set?: boolean, contains?: unknown }
	| { all: Predicate[] }
	| { any: Predicate[] }
	| { not: Predicate }

export type ValueSource = Record<string, unknown> | ((name: string) => unknown)

/** The values a `schema` field's chosen source gives: the names and what they read. */
export const DERIVED = ["features", "keepsList"] as const

/**
 * The same values, plus the ones derived from the source each `schema` field in `fields` (children included) has chosen. `list` is what the form offers the
 * field to choose from, each choice carrying its source's `features` and `keepsList`.
 */
export function derivedValues(fields: FormField[], values: ValueSource): (name: string) => unknown {
	const chosen = (name: string) => typeof values === "function" ? values(name) : values?.[name]
	const find = (list: FormField[], name: string): FormField | undefined => {
		for (const px of list) {
			if (px.name === name) return px
			const inChild = px.children ? find(px.children, name) : undefined
			if (inChild) return inChild
		}
		return undefined
	}
	return (name: string) => {
		const dot = name.lastIndexOf(".")
		const kind = dot < 0 ? undefined : name.slice(dot + 1)
		if (kind && (DERIVED as readonly string[]).includes(kind)) {
			const field = find(fields, name.slice(0, dot))
			if (field?.type === "schema") {
				const pick = (field.list ?? []).find(item => item.value === chosen(field.name)) as { features?: string[], keepsList?: boolean } | undefined
				return kind === "features" ? (pick?.features ?? []) : (pick?.keepsList === true)
			}
		}
		return chosen(name)
	}
}

const read = (values: ValueSource, name: string): unknown => {
	const v = typeof values === "function" ? values(name) : values?.[name]
	return v === undefined || v === "" ? null : v
}

/** True when the predicate holds. A predicate this code does not understand holds (the field stays visible) and is reported by `findProblems`. */
export function evaluate(p: unknown, values: ValueSource): boolean {
	if (!p || typeof p !== "object") return true
	const o = p as Record<string, unknown>
	if (Array.isArray(o.all)) return o.all.every(x => evaluate(x, values))
	if (Array.isArray(o.any)) return o.any.some(x => evaluate(x, values))
	if ("not" in o) return !evaluate(o.not, values)
	if (typeof o.field === "string") {
		const v = read(values, o.field)
		if ("const" in o) return v === (o.const === undefined ? null : o.const)
		if (Array.isArray(o.enum)) return o.enum.includes(v)
		if (typeof o.set === "boolean") return (v !== null) === o.set
		if ("contains" in o) return Array.isArray(v) && v.includes(o.contains)
	}
	return true
}

export const isVisible = (px: { visibleIf?: unknown }, values: ValueSource): boolean => evaluate(px.visibleIf, values)

/** Names of the fields that are hidden for these values, children of a hidden `schema` field included. */
export function hiddenNames(fields: FormField[], values: ValueSource, into: Set<string> = new Set(), parentHidden = false, derived: ValueSource = derivedValues(fields, values)): Set<string> {
	for (const px of fields) {
		if (px.type === "header") continue
		const hidden = parentHidden || !isVisible(px as { visibleIf?: unknown }, derived)
		if (hidden) into.add(px.name)
		if (px.children) hiddenNames(px.children, values, into, hidden, derived)
	}
	return into
}

/** The field names a predicate refers to. */
export function referencedFields(p: unknown): string[] {
	if (!p || typeof p !== "object") return []
	const o = p as Record<string, unknown>
	if (Array.isArray(o.all)) return o.all.flatMap(referencedFields)
	if (Array.isArray(o.any)) return o.any.flatMap(referencedFields)
	if ("not" in o) return referencedFields(o.not)
	return typeof o.field === "string" ? [o.field] : []
}

const OPERATORS = ["const", "enum", "set", "contains"]
function shapeProblem(p: unknown): string | null {
	if (!p || typeof p !== "object" || Array.isArray(p)) return "is not an object"
	const o = p as Record<string, unknown>
	if (Array.isArray(o.all) || Array.isArray(o.any)) {
		for (const x of (o.all ?? o.any) as unknown[]) {
			const m = shapeProblem(x)
			if (m) return m
		}
		return null
	}
	if ("not" in o) return shapeProblem(o.not)
	if (typeof o.field !== "string") return "needs a field, all, any or not"
	return OPERATORS.some(op => op in o) ? null : "needs const, enum, set or contains"
}

/** `<schema field>.features` and the like: a value derived from a source a `schema` field chose, not a field of its own. */
const isDerived = (name: string, properties: { name: string, type?: string }[]): boolean => {
	const dot = name.lastIndexOf(".")
	return dot > 0 && (DERIVED as readonly string[]).includes(name.slice(dot + 1)) && properties.some(p => p.name === name.slice(0, dot) && p.type === "schema")
}

/** What is wrong with the `visibleIf` of these properties: a malformed predicate, a name that is no field, or a cycle. Empty when fine. */
export function findProblems(properties: { name: string, type?: string, visibleIf?: unknown }[]): string[] {
	const problems: string[] = []
	const names = new Set(properties.filter(p => p.type !== "header").map(p => p.name))
	const edges = new Map<string, string[]>()
	for (const px of properties) {
		if (px.visibleIf === undefined) continue
		const shape = shapeProblem(px.visibleIf)
		if (shape) problems.push(`${px.name}: visibleIf ${shape}`)
		const refs = referencedFields(px.visibleIf)
		for (const r of refs) {
			if (!names.has(r) && !isDerived(r, properties)) problems.push(`${px.name}: visibleIf refers to unknown field '${r}'`)
		}
		edges.set(px.name, refs.filter(r => names.has(r)))
	}
	const state = new Map<string, 1 | 2>()
	const visit = (n: string, path: string[]): void => {
		if (state.get(n) === 2) return
		if (state.get(n) === 1) {
			problems.push(`visibleIf cycle: ${[...path.slice(path.indexOf(n)), n].join(" -> ")}`)
			return
		}
		state.set(n, 1)
		for (const m of edges.get(n) ?? []) visit(m, [...path, n])
		state.set(n, 2)
	}
	for (const n of edges.keys()) visit(n, [])
	return problems
}
