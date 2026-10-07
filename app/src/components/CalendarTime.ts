// Calendar arithmetic for the timeline. Days are `YYYY-MM-DD` keys and times are minutes since midnight, both read in one
// time zone (the device's), so nothing here adds 24 hours to a date: a day with 23 or 25 hours is still one day.

export type TimeRange = {
	start: number
	end: number
	interval: number
}
export const MINUTES_PER_DAY = 1440

const formatters = new Map<string, Intl.DateTimeFormat>()
function formatterFor(timeZone: string|undefined): Intl.DateTimeFormat {
	const cacheKey = timeZone ?? ""
	let formatter = formatters.get(cacheKey)
	if(!formatter) {
		const options: Intl.DateTimeFormatOptions = { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }
		try {
			formatter = new Intl.DateTimeFormat("en-CA", { ...options, timeZone })
		}
		catch {
			// a name this browser does not know: show the browser's own zone rather than nothing
			formatter = new Intl.DateTimeFormat("en-CA", options)
		}
		formatters.set(cacheKey, formatter)
	}
	return formatter
}

/** The calendar day and the minute of that day at `instant`, in `timeZone` (the browser's zone when not given). */
export function zonedParts(instant: Date, timeZone?: string): { key: string, minutes: number } {
	const parts: Record<string, string> = {}
	for(const part of formatterFor(timeZone).formatToParts(instant)) parts[part.type] = part.value
	return {
		key: `${parts.year!.padStart(4, "0")}-${parts.month}-${parts.day}`,
		minutes: Number(parts.hour) * 60 + Number(parts.minute)
	}
}

function fromKey(key: string): Date {
	const [year, month, day] = key.split("-").map(Number)
	return new Date(Date.UTC(year!, month! - 1, day!))
}
function toKey(date: Date): string {
	return `${String(date.getUTCFullYear()).padStart(4, "0")}-${String(date.getUTCMonth() + 1).padStart(2, "0")}-${String(date.getUTCDate()).padStart(2, "0")}`
}
/** The day `count` days after `key` (negative before): calendar arithmetic, so a daylight-saving day is still one day. */
export function addDays(key: string, count: number): string {
	const date = fromKey(key)
	date.setUTCDate(date.getUTCDate() + count)
	return toKey(date)
}
export function daysFrom(first: string, count: number): string[] {
	return Array.from({ length: Math.max(0, count) }, (_, index) => addDays(first, index))
}
/** What a header shows for a day: weekday (0 = Sunday) and day of month, plus a Date whose local fields are that calendar date. */
export function dayInfo(key: string): { weekday: number, dayOfMonth: number, date: Date } {
	const utc = fromKey(key)
	return {
		weekday: utc.getUTCDay(),
		dayOfMonth: utc.getUTCDate(),
		date: new Date(utc.getUTCFullYear(), utc.getUTCMonth(), utc.getUTCDate(), 12)
	}
}

export type Segment = {
	/** the day this part is drawn on */
	day: string
	/** minutes since midnight at which it starts */
	start: number
	/** how many minutes it lasts on this day */
	length: number
	/** it began on an earlier day */
	continued: boolean
}
/** An event is drawn on every day it touches: it is cut at midnight (at most `maxDays` days). */
export function segments(day: string, startMinutes: number, duration: number, maxDays = 62): Segment[] {
	const result: Segment[] = []
	let remaining = Math.max(1, duration)
	let start = startMinutes
	let current = day
	let continued = false
	while(remaining > 0 && result.length < maxDays) {
		const length = Math.min(remaining, MINUTES_PER_DAY - start)
		result.push({ day: current, start, length, continued })
		remaining -= length
		start = 0
		current = addDays(current, 1)
		continued = true
	}
	return result
}

export function slotCount(range: TimeRange): number {
	return Math.max(0, Math.ceil((range.end - range.start) / range.interval))
}
/** The grid cells of the time column: row 1 is the slot that starts at `range.start`. */
export function timeSlots(range: TimeRange): { minutes: number, hour: number, minute: number, index: number, row: number }[] {
	return Array.from({ length: slotCount(range) }, (_, index) => {
		const minutes = range.start + index * range.interval
		return { minutes, hour: Math.floor(minutes / 60) % 24, minute: minutes % 60, index, row: index + 1 }
	})
}
/** The rows a segment covers: the slot it starts in (not the nearest one), as many as it lasts; null when it is outside the shown times. */
export function place(segment: Pick<Segment, "start" | "length">, range: TimeRange): { row: number, span: number } | null {
	const from = Math.max(segment.start, range.start)
	const to = Math.min(segment.start + segment.length, range.end)
	if(to <= from) return null
	const first = Math.floor((from - range.start) / range.interval)
	const last = Math.ceil((to - range.start) / range.interval)
	return { row: first + 1, span: Math.max(1, last - first) }
}
