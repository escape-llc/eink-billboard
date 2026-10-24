/**
 * A URL lookup that takes parameters (#510 A8). `with` names fields whose values go as query parameters (the form's fields, or a list row's), and
 * the list is fetched again when one changes; `search` sends what was typed in the field's search box as `q`. The route declares each as a query
 * parameter (TestDescriptorAddresses checks), so the server answers the list for those values.
 */
import type { LookupValue } from "./FormDefs"

/** What a field's lookup asks for: the address with its query, or the first named field that has no value yet (the list waits for it). */
export type LookupAddress = { address: string, missing?: undefined } | { address?: undefined, missing: string }

const unset = (value: unknown) => value === undefined || value === null || value === "" || (Array.isArray(value) && value.length === 0)

/**
 * The address of a lookup for the values it needs: `read` gives a named field's value. A list value (a multi-select) is one parameter per
 * value; anything that is not a string, a number or a boolean is not sent. `q` is the search text (none: no `q`).
 */
export function lookupAddress(url: string, withNames: string[] | undefined, read: (name: string) => unknown, q?: string): LookupAddress {
	const query = new URLSearchParams()
	for (const name of withNames ?? []) {
		const value = read(name)
		if (unset(value)) return { missing: name }
		for (const one of Array.isArray(value) ? value : [value]) {
			if (["string", "number", "boolean"].includes(typeof one)) query.append(name, String(one))
		}
	}
	if (q !== undefined) query.append("q", q)
	const text = query.toString()
	return { address: text ? `${url}${url.includes("?") ? "&" : "?"}${text}` : url }
}

/**
 * A list with the stored value(s) kept when it does not offer them (renamed, or not in this answer): a value must not look unset. `known` names a
 * value an earlier answer had (a search that no longer finds the choice made); otherwise the value is its own name.
 */
export function withStored(list: LookupValue[], stored: unknown, known?: (value: unknown) => string | undefined): LookupValue[] {
	const missing = (Array.isArray(stored) ? stored : [stored]).filter(v => !unset(v) && !list.some(lx => lx.value === v))
	return [...list, ...missing.map(v => ({ name: known?.(v) ?? String(v), value: v }))]
}
