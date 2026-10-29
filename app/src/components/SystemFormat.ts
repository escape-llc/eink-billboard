/** The words the System page uses for sizes and times. */
import type { MaterialIconName } from "./MaterialIcons"

const UNITS = ["B", "KB", "MB", "GB", "TB"]

/** A size in bytes as people read it, short for a pill: `0 B`, `1.5 KB`, `38 MB`. */
export function formatBytes(value: number | null | undefined): string {
	if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return "?"
	let size = value
	let unit = 0
	while (size >= 1024 && unit < UNITS.length - 1) {
		size /= 1024
		unit++
	}
	// whole numbers from 10 up, one decimal below, and no decimal for single bytes
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

/**
 * One pill of a System card (#796): its label on the tone of what it means (`neutral` is no judgment), its value beside it. `icon` is a glyph shown in place of the label
 * where its meaning is plain (the label is still the pill's name for a screen reader, and the title says it in words); `testid` names a pill a test reads.
 */
export type PillKind = AnswerKind | "neutral"
export type Pill = { label: string, value: string, kind: PillKind, title: string, icon?: MaterialIconName, testid?: string }

/** An API data source's month as pills for the closed API usage card: `calls 70`, `failed 2` (only when some failed), `cache 75%`, and `quota 62%` when a plan is set. */
export function usagePills(month: { calls: number, status?: Record<string, number> | null, hitRate?: number | null }, quota?: { percent: number, limit: number, used: number } | null): Pill[] {
	const pills: Pill[] = [{ label: "calls", value: String(month.calls), kind: "neutral", title: "Calls this month", icon: "swap_vert" }]
	const failed = failedCalls(month.status)
	if (failed) pills.push({ label: "failed", value: String(failed), kind: "danger", title: `${failed} of this month's calls failed`, icon: "error" })
	if (typeof month.hitRate === "number" && Number.isFinite(month.hitRate)) pills.push({ label: "cache", value: formatShare(month.hitRate), kind: "neutral", title: "Lookups answered without a download this month", icon: "cached" })
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
		{ label: "size", value: formatBytes(bytes), kind: "neutral", title: "What the device keeps, in all", icon: "database" },
		{ label: "files", value: String(files), kind: "neutral", title: `${files} ${files === 1 ? "file" : "files"} in all`, icon: "description" },
	]
	if (!volume?.total) return pills
	const share = bytes / volume.total * 100
	pills.push({ label: "disk", value: share > 0 && share < 0.1 ? "<0.1%" : `${share.toFixed(1).replace(/\.0$/, "")}%`, kind: "neutral", title: "The device's share of the disk" })
	pills.push({ label: "free", value: formatBytes(volume.free), kind: gaugeSeverity(volume.percent), title: `${formatBytes(volume.free)} of ${formatBytes(volume.total)} free; the disk is ${Math.round(volume.percent)}% full`, icon: "hard_drive" })
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

/** What each part of the start is, as a glyph (the Device card): the display, the playlist and the timer tasks. */
const PART_ICONS: Record<string, MaterialIconName> = { "display": "tv", "playlist-layer": "playlist_play", "timer-layer": "schedule" }

/**
 * The application as pills (the Device card's Application row): each part of the start with its glyph, running, failed or starting on its tone (the title is what
 * the part said), the memory the application uses when the machine can say, and what it keeps on disk in all (the Storage card's size, the same pill).
 */
export function devicePills(components: Record<string, { state: string, message: string }>, titles: Record<string, string>, appMemory?: number | null,
		storage?: { files: number, bytes: number }[] | null): Pill[] {
	const pills: Pill[] = Object.entries(components).map(([name, c]) => {
		const label = titles[name] ?? name
		const [value, kind]: [string, PillKind] = c.state === "ok" ? ["running", "success"] : c.state === "failed" ? ["failed", "danger"] : ["starting", "info"]
		return { label, value, kind, title: `${label}: ${c.message}`, icon: PART_ICONS[name], testid: `part-${name}` }
	})
	if (typeof appMemory === "number") pills.push({ label: "memory", value: formatBytes(appMemory), kind: "neutral", title: "The memory the application uses", icon: "memory_alt", testid: "app-memory" })
	if (storage) {
		const [size] = storagePills(storage)
		pills.push({ ...size, title: `${size.title}: ${storageLine(storage)}`, testid: "app-storage" })
	}
	return pills
}

type Host = { os: string, os_release: string, machine: string, python: string, cpus: number, commit: string, uptime_seconds?: number | null, app_uptime_seconds?: number | null, clock?: "synced" | "unsynced" | null }
type Load = { cpu_percent?: number | null, load?: number[] | null, memory?: { total: number, used: number, percent: number } | null, app_memory?: number | null }
type Volume = { total: number, free: number, percent: number }

/** The machine as pills (the Device card's Machine row, #796): what it runs, the builds, how long it and the app have been up, the clock, the processor, the memory and the disk. A reading it cannot give is left out. */
export function machinePills(host: Host, load: Load, volume: Volume | null | undefined, webCommit: string, mismatch: boolean): Pill[] {
	const pills: Pill[] = [
		{ label: "system", value: `${host.os} ${host.os_release}`.trim(), kind: "neutral", title: `${host.os} ${host.os_release} (${host.machine})`, icon: "computer" },
		{ label: "build", value: host.commit === webCommit ? host.commit : `${host.commit} / ${webCommit}`, kind: mismatch ? "warn" : "neutral", testid: "builds",
			title: mismatch ? `Different builds: the server is ${host.commit}, this page ${webCommit}. Reload the page.` : `Server ${host.commit}, web app ${webCommit}` },
		{ label: "python", value: host.python, kind: "neutral", title: `Python ${host.python}` },
	]
	if (typeof host.uptime_seconds === "number") pills.push({ label: "up", value: formatUptime(host.uptime_seconds), kind: "neutral", title: `The machine has been up for ${formatUptime(host.uptime_seconds)}`, icon: "power_settings_new" })
	if (typeof host.app_uptime_seconds === "number") pills.push({ label: "app", value: formatUptime(host.app_uptime_seconds), kind: "neutral", title: `The app has been running for ${formatUptime(host.app_uptime_seconds)}`, icon: "timer", testid: "app-uptime" })
	if (host.clock === "synced") pills.push({ label: "clock", value: "set", kind: "success", title: "The clock was set by the network", icon: "sync", testid: "clock" })
	else if (host.clock === "unsynced") pills.push({ label: "clock", value: "not set", kind: "warn", title: "The clock is not set yet: what shows the time may be wrong", icon: "sync_problem", testid: "clock" })
	const busy = typeof load.cpu_percent === "number" ? ` · ${load.cpu_percent}%` : ""
	pills.push({ label: "processor", value: `${host.cpus} ${host.cpus === 1 ? "core" : "cores"}${busy}`, kind: "neutral", icon: "memory",
		title: `${host.cpus} ${host.cpus === 1 ? "core" : "cores"}${busy ? `, ${load.cpu_percent}% busy` : ""}${load.load ? ` (load ${load.load.join(" ")})` : ""}` })
	if (load.memory) pills.push({ label: "memory", value: `${formatBytes(load.memory.used)} / ${formatBytes(load.memory.total)}`, kind: gaugeSeverity(load.memory.percent), icon: "memory_alt", testid: "memory",
		title: `Memory: ${formatBytes(load.memory.used)} of ${formatBytes(load.memory.total)} in use (${Math.round(load.memory.percent)}%)` })
	if (volume?.total) pills.push({ label: "disk", value: `${formatBytes(volume.free)} free`, kind: gaugeSeverity(volume.percent), icon: "hard_drive", testid: "disk",
		title: `Disk: ${formatBytes(volume.free)} free of ${formatBytes(volume.total)} (${Math.round(volume.percent)}% in use)` })
	return pills
}

type Pi = { model: string, temperature_c?: number | null, cpu_mhz?: number | null, cpu_max_mhz?: number | null, fan_rpm?: number | null, fan_percent?: number | null, throttled?: string[] | null }

/** A Raspberry Pi's own readings as pills: the model, the temperature on its tone, the clock speed, the fan, and the power warnings (none is one green pill). */
export function piPills(pi: Pi): Pill[] {
	const pills: Pill[] = [{ label: "model", value: pi.model, kind: "neutral", title: pi.model, icon: "developer_board" }]
	if (typeof pi.temperature_c === "number") pills.push({ label: "temperature", value: `${pi.temperature_c} °C`, kind: temperatureSeverity(pi.temperature_c), title: `Temperature ${pi.temperature_c} °C`, icon: "thermostat" })
	if (typeof pi.cpu_mhz === "number") pills.push({ label: "speed", value: `${pi.cpu_mhz} MHz`, kind: "neutral", title: `The processor runs at ${pi.cpu_mhz} MHz${pi.cpu_max_mhz ? `, up to ${pi.cpu_max_mhz}` : ""}`, icon: "speed" })
	const fan = fanText(pi.fan_rpm, pi.fan_percent)
	if (fan) pills.push({ label: "fan", value: fan, kind: "neutral", title: `Fan: ${fan}`, icon: "mode_fan", testid: "fan" })
	if (pi.throttled) {
		if (pi.throttled.length === 0) pills.push({ label: "power", value: "ok", kind: "success", title: "No power warnings", icon: "bolt" })
		for (const w of pi.throttled) pills.push({ label: "power", value: w, kind: w.endsWith("now") ? "danger" : "warn", title: `Power: ${w}`, icon: "bolt" })
	}
	return pills
}

/** The storage's areas, or one group's plugins or data sources, as pills (the open Storage card): the name and its size; the files and what is kept are in the title. */
export function sizePills(items: { name: string, files: number, bytes: number, kept?: number | null }[]): Pill[] {
	return items.map(i => ({ label: i.name, value: formatBytes(i.bytes), kind: "neutral" as const,
		title: `${i.name}: ${formatBytes(i.bytes)} in ${i.files} ${i.files === 1 ? "file" : "files"}${i.kept ? `, ${formatBytes(i.kept)} of it kept (can be fetched again)` : ""}` }))
}

type Period = { calls: number, status?: Record<string, number> | null, sent: number, received: number, hitRate?: number | null, bytesSaved?: number | null }

/** One period of an API data source as pills (the open API usage card): the calls, the failed ones, the bytes sent and received, and the cache's share. */
export function periodPills(label: string, period: Period): Pill[] {
	const pills: Pill[] = [{ label: "calls", value: String(period.calls), kind: "neutral", title: `${label}: ${period.calls} calls`, icon: "swap_vert" }]
	const failed = failedCalls(period.status)
	if (failed) pills.push({ label: "failed", value: String(failed), kind: "danger", title: `${label}: ${failed} failed`, icon: "error" })
	pills.push({ label: "sent", value: formatBytes(period.sent), kind: "neutral", title: `${label}: ${formatBytes(period.sent)} sent`, icon: "upload" })
	pills.push({ label: "received", value: formatBytes(period.received), kind: "neutral", title: `${label}: ${formatBytes(period.received)} received`, icon: "download" })
	if (typeof period.hitRate === "number" && Number.isFinite(period.hitRate)) pills.push({ label: "cache", value: formatShare(period.hitRate), kind: "neutral", icon: "cached",
		title: `${label}: ${formatShare(period.hitRate)} of the lookups answered without a download${period.bytesSaved ? `, ${formatBytes(period.bytesSaved)} saved` : ""}` })
	return pills
}
