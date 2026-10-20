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

/** The Pi's temperature as a word: the firmware throttles at 80 C and is soft limited from 60. */
export function temperatureSeverity(celsius: number | null | undefined): "success" | "warn" | "danger" {
	if (typeof celsius !== "number") return "success"
	return celsius >= 80 ? "danger" : celsius >= 70 ? "warn" : "success"
}
