import { OpenStreetMapProvider } from 'leaflet-geosearch';

/** A place an address search found: its name and where it is. */
export type Place = { label: string, latitude: number, longitude: number }

/** What asks the search service for one text. */
export type Ask = (query: string) => Promise<Place[]>

export type Clock = { now: () => number, sleep: (ms: number) => Promise<void> }

/** Nominatim's usage policy: at most one request a second. */
export const MIN_INTERVAL_MS = 1000
/** The shortest text worth asking for. */
export const MIN_QUERY_LENGTH = 3
/** How many answers are kept (the policy asks for results to be cached on our side). */
export const KEPT_ANSWERS = 50

const realClock: Clock = { now: () => Date.now(), sleep: ms => new Promise(resolve => setTimeout(resolve, ms)) }

/** The text as it is asked for: trimmed, one space between words. */
export function normalQuery(text: string | undefined): string {
	return (text ?? "").trim().replace(/\s+/g, " ")
}

/**
 * A search that follows Nominatim's usage policy: it runs only when asked (never as you type), one at a time
 * (a search while one runs answers `null`: ignored), at most one request a second (a later one waits its turn),
 * and an answer is kept, so the same text again sends nothing.
 * A failed request is not kept and its error reaches the caller.
 */
export function addressSearch(ask: Ask, clock: Clock = realClock) {
	const kept = new Map<string, Place[]>()
	let busy = false
	let last = -Infinity
	return async function search(text: string | undefined): Promise<Place[] | null> {
		const query = normalQuery(text)
		if (query.length < MIN_QUERY_LENGTH) return []
		const key = query.toLowerCase()
		const known = kept.get(key)
		if (known !== undefined) return known
		if (busy) return null
		busy = true
		try {
			const wait = last + MIN_INTERVAL_MS - clock.now()
			if (wait > 0) await clock.sleep(wait)
			last = clock.now()
			const places = await ask(query)
			if (kept.size >= KEPT_ANSWERS) kept.delete(kept.keys().next().value!)
			kept.set(key, places)
			return places
		}
		finally {
			busy = false
		}
	}
}

/** OpenStreetMap's Nominatim, through leaflet-geosearch. */
const nominatim: Ask = async (query) => {
	const results = await new OpenStreetMapProvider().search({ query })
	return results.map(r => ({ label: r.label, latitude: r.y, longitude: r.x }))
}

/** The one search of the page: every location picker shares it, so the limit holds for the browser, not per field. */
export const searchAddress = addressSearch(nominatim)
