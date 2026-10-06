/** The date fields of a form hold `YYYY-MM-DD` strings (what the server stores); PrimeVue's DatePicker works with `Date`. */
const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/

/** Local-midnight `Date` for an ISO date string, or `null` when it is empty or not a valid date. */
export function isoToDate(value: unknown): Date | null {
	if (typeof value !== "string") return null
	const m = ISO_DATE.exec(value)
	if (!m) return null
	const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])]
	const date = new Date(y, mo - 1, d)
	// reject 2026-02-31 style dates that `Date` would roll over
	return date.getFullYear() === y && date.getMonth() === mo - 1 && date.getDate() === d ? date : null
}

/** `YYYY-MM-DD` from the local calendar day of a `Date`, or `null` when there is none. */
export function dateToIso(date: Date | null | undefined): string | null {
	if (!date) return null
	const pad = (n: number, w = 2) => String(n).padStart(w, "0")
	return `${pad(date.getFullYear(), 4)}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}
