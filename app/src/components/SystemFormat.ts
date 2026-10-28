/** The words the System page uses for sizes and times. */

const UNITS = ["bytes", "KB", "MB", "GB", "TB"]

/** A size in bytes as people read it: `0 bytes`, `1.5 KB`, `38 MB`. */
export function formatBytes(value: number | null | undefined): string {
	if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return "?"
	let size = value
	let unit = 0
	while (size >= 1024 && unit < UNITS.length - 1) {
		size /= 1024
		unit++
	}
	// whole numbers from 10 up, one decimal below, and no decimal for bytes
	const text = unit === 0 || size >= 10 ? String(Math.round(size)) : size.toFixed(1).replace(/\.0$/, "")
	return `${text} ${UNITS[unit]}`
}

/** How long, as `3 days 4 h`, `2 h 5 min`, `45 min` or `30 s`: the two largest units. */
export function formatUptime(seconds: number | null | undefined): string {
	if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return "?"
	const days = Math.floor(seconds / 86400)
	const hours = Math.floor((seconds % 86400) / 3600)
	const minutes = Math.floor((seconds % 3600) / 60)
	if (days > 0) return `${days} ${days === 1 ? "day" : "days"} ${hours} h`
	if (hours > 0) return `${hours} h ${minutes} min`
	if (minutes > 0) return `${minutes} min`
	return `${Math.floor(seconds)} s`
}

/** The colour word of a gauge: warn from 75 percent, danger from 90. */
export function gaugeSeverity(percent: number | null | undefined): "success" | "warn" | "danger" {
	if (typeof percent !== "number") return "success"
	return percent >= 90 ? "danger" : percent >= 75 ? "warn" : "success"
}

/**
 * The Pi's fan in words: its speed when it reports one, else how hard it is driven. A fan without a speed wire (or too slow to count) reads 0 rpm while it is driven,
 * so it is off only when the drive is 0 too.
 */
export function fanText(rpm: number | null | undefined, percent: number | null | undefined): string {
	const drive = typeof percent === "number" && percent > 0 ? `${percent}% power` : ""
	if (typeof rpm === "number" && rpm > 0) return drive ? `${rpm} rpm (${drive})` : `${rpm} rpm`
	if (drive) return `${drive}, no speed reported`
	return typeof percent === "number" || rpm === 0 ? "Off" : ""
}

/** The Pi's temperature as a word: the firmware throttles at 80 C and is soft limited from 60. */
export function temperatureSeverity(celsius: number | null | undefined): "success" | "warn" | "danger" {
	if (typeof celsius !== "number") return "success"
	return celsius >= 80 ? "danger" : celsius >= 70 ? "warn" : "success"
}

/** A call that did not succeed: no answer at all (`timeout`, `connect`, `tls`, `error`) or an HTTP status from 400 up. */
export function failedCalls(status: Record<string, number> | null | undefined): number {
	let failed = 0
	for (const [code, count] of Object.entries(status ?? {})) {
		const number = Number(code)
		if (Number.isNaN(number) || number >= 400) failed += count
	}
	return failed
}

/** What an answer means, as the tone of its pill: 2xx success, 3xx info, 4xx warn, and 5xx or no answer at all (`timeout`, `connect`, `tls`, `error`) danger. */
export type AnswerKind = "success" | "info" | "warn" | "danger"

export function answerKind(code: string): AnswerKind {
	const n = Number(code)
	if (Number.isNaN(n)) return "danger"
	return n >= 500 ? "danger" : n >= 400 ? "warn" : n >= 300 ? "info" : n >= 200 ? "success" : "info"
}

/** What a status means, in words, for its pill's title: the HTTP statuses a service is likely to answer, and the ways of getting no answer at all. */
const ANSWER_NAMES: Record<string, string> = {
	"200": "OK", "201": "Created", "202": "Accepted", "204": "No Content", "206": "Partial Content",
	"301": "Moved Permanently", "302": "Found", "303": "See Other", "304": "Not Modified", "307": "Temporary Redirect", "308": "Permanent Redirect",
	"400": "Bad Request", "401": "Unauthorized", "402": "Payment Required", "403": "Forbidden", "404": "Not Found", "405": "Method Not Allowed",
	"406": "Not Acceptable", "408": "Request Timeout", "409": "Conflict", "410": "Gone", "413": "Content Too Large", "415": "Unsupported Media Type",
	"422": "Unprocessable Content", "429": "Too Many Requests",
	"500": "Internal Server Error", "501": "Not Implemented", "502": "Bad Gateway", "503": "Service Unavailable", "504": "Gateway Timeout",
	"timeout": "no answer in time", "connect": "could not connect", "tls": "the secure connection failed", "error": "no answer",
}

export function answerName(code: string): string {
	return ANSWER_NAMES[code] ?? ""
}

/** The calls by what the service answered, one pill each: the status codes in order, then the calls with no answer at all (`timeout`...) by name. */
export function answerPills(status: Record<string, number> | null | undefined): { code: string, count: number, kind: AnswerKind, title: string }[] {
	const order = (code: string) => { const n = Number(code); return Number.isNaN(n) ? Infinity : n }
	return Object.entries(status ?? {})
		.sort((a, b) => order(a[0]) - order(b[0]) || a[0].localeCompare(b[0]))
		.map(([code, count]) => {
			const name = answerName(code)
			const calls = `${count} ${count === 1 ? "call" : "calls"}`
			const title = Number.isNaN(Number(code)) ? `${calls}: ${name || code}` : `${code}${name ? ` ${name}` : ""}: ${calls}`
			return { code, count, kind: answerKind(code), title }
		})
}

/** A share (0 to 1) as `86%`; nothing counted is a dash. */
export function formatShare(share: number | null | undefined): string {
	return typeof share === "number" && Number.isFinite(share) ? `${Math.round(share * 100)}%` : "–"
}

/** The device's wall clock from a moment the server sent (`2026-10-21T12:17:09.5+02:00` is `2026-10-21 12:17`): the offset is the device's own, so the text is read as written, not in the browser's zone. */
export function deviceMoment(moment: string | null | undefined): string {
	const found = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(moment ?? "")
	return found ? `${found[1]} ${found[2]}` : ""
}

/** One pill of the usage card: its label on the tone of what it means (`neutral` is no judgment), its value beside it. */
export type PillKind = AnswerKind | "neutral"
export type Pill = { label: string, value: string, kind: PillKind, title: string }

/** An API data source's month as pills for the closed API usage card: `calls 70`, `failed 2` (only when some failed), `cache 75%`, and `quota 62%` when a plan is set. */
export function usagePills(month: { calls: number, status?: Record<string, number> | null, hitRate?: number | null }, quota?: { percent: number, limit: number, used: number } | null): Pill[] {
	const pills: Pill[] = [{ label: "calls", value: String(month.calls), kind: "neutral", title: "Calls this month" }]
	const failed = failedCalls(month.status)
	if (failed) pills.push({ label: "failed", value: String(failed), kind: "danger", title: `${failed} of this month's calls failed` })
	if (typeof month.hitRate === "number" && Number.isFinite(month.hitRate)) pills.push({ label: "cache", value: formatShare(month.hitRate), kind: "neutral", title: "Lookups answered without a download this month" })
	if (quota) pills.push({ label: "quota", value: `${Math.round(quota.percent)}%`, kind: quotaSeverity(quota.percent), title: `${quota.used} of ${quota.limit} calls of the plan this period` })
	return pills
}

/** The plan's quota as a colour word: warn from 80 percent of the calls, danger at the quota (#586). */
export function quotaSeverity(percent: number | null | undefined): "success" | "warn" | "danger" {
	if (typeof percent !== "number") return "success"
	return percent >= 100 ? "danger" : percent >= 80 ? "warn" : "success"
}

/** The warning above a source's bar, in words (a colour alone is not enough): none under 80 percent. */
export function quotaWarning(percent: number | null | undefined): string {
	if (typeof percent !== "number") return ""
	return percent >= 100 ? "The quota is used up" : percent >= 80 ? "Over 80% of the quota is used" : ""
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

/** One plan period in a line, for the card: `620 of 1000 calls since Oct 5 (62%), resets Nov 5`. The dates are the device's days (`YYYY-MM-DD`). */
export function quotaLine(q: { limit: number, used: number, percent: number, since: string, resets: string }): string {
	const day = (iso: string) => { const [, m, d] = iso.split("-").map(Number); return `${MONTHS[(m ?? 1) - 1] ?? "?"} ${d}` }
	return `${q.used} of ${q.limit} calls since ${day(q.since)} (${Math.round(q.percent)}%), resets ${day(q.resets)}`
}

/** What the storage holds in all: its areas added up, and its share of the disk it is on when that is known (`12 MB in 140 files, 0.1% of the disk`). */
/** The storage as pills for the closed Storage card: `size 73 MB`, `files 226`, and with the disk known `disk <0.1%` (our share of it) and `free 12 GB`, toned by how full the disk is. */
export function storagePills(areas: { files: number, bytes: number }[], volume?: { total: number, free: number, percent: number } | null): Pill[] {
	const files = areas.reduce((sum, a) => sum + a.files, 0)
	const bytes = areas.reduce((sum, a) => sum + a.bytes, 0)
	const pills: Pill[] = [
		{ label: "size", value: formatBytes(bytes), kind: "neutral", title: "What the device keeps, in all" },
		{ label: "files", value: String(files), kind: "neutral", title: `${files} ${files === 1 ? "file" : "files"} in all` },
	]
	if (!volume?.total) return pills
	const share = bytes / volume.total * 100
	pills.push({ label: "disk", value: share > 0 && share < 0.1 ? "<0.1%" : `${share.toFixed(1).replace(/\.0$/, "")}%`, kind: "neutral", title: "The device's share of the disk" })
	pills.push({ label: "free", value: formatBytes(volume.free), kind: gaugeSeverity(volume.percent), title: `${formatBytes(volume.free)} of ${formatBytes(volume.total)} free; the disk is ${Math.round(volume.percent)}% full` })
	return pills
}

export function storageLine(areas: { files: number, bytes: number }[], volume?: { total: number } | null): string {
	const files = areas.reduce((sum, a) => sum + a.files, 0)
	const bytes = areas.reduce((sum, a) => sum + a.bytes, 0)
	const text = `${formatBytes(bytes)} in ${files} ${files === 1 ? "file" : "files"}`
	if (!volume?.total) return text
	const share = bytes / volume.total * 100
	return `${text}, ${share > 0 && share < 0.1 ? "less than 0.1" : share.toFixed(1).replace(/\.0$/, "")}% of the disk`
}
