/**
 * What the Scheduler shows: a day, a week, or a list of the tasks, from an offset in days from today (in the device's zone).
 * The week is the seven days from the day shown, so it starts on today's weekday (not a calendar week), and nothing before today is shown.
 */
import { addDays } from "./CalendarTime"

export type SchedulerMode = "day" | "week" | "list"
export const MODES: { value: SchedulerMode, label: string, icon: string }[] = [
	{ value: "day", label: "Day", icon: "mi mi-calendar-view-day" },
	{ value: "week", label: "Week", icon: "mi mi-calendar-view-week" },
	{ value: "list", label: "List", icon: "mi mi-view-list" },
]

/** The days a mode shows at once, and how far back and forward move. */
export function daysOf(mode: SchedulerMode): number {
	return mode === "day" ? 1 : 7
}

/** The offset after moving `direction` (+1 forward, -1 back) in a mode: never before today. */
export function step(mode: SchedulerMode, offset: number, direction: 1 | -1): number {
	return Math.max(0, offset + direction * daysOf(mode))
}

/** The offset in another mode: a week (and the list, which covers a week) starts a whole number of weeks from today, so its weekday is today's. */
export function switchMode(mode: SchedulerMode, offset: number): number {
	return mode === "day" ? Math.max(0, offset) : Math.floor(Math.max(0, offset) / 7) * 7
}

/** The first day and how many days to ask the server for. */
export function windowOf(mode: SchedulerMode, today: string, offset: number): { start: string, days: number } {
	return { start: addDays(today, Math.max(0, offset)), days: daysOf(mode) }
}

/** The days shown, as words: "Tue Oct 13" or "Tue Oct 13 – Mon Oct 19". */
export function rangeLabel(start: string, days: number): string {
	const format = new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" })
	const at = (key: string) => { const [y, m, d] = key.split("-").map(Number); return format.format(new Date(Date.UTC(y!, m! - 1, d!))).replace(",", "") }
	return days <= 1 ? at(start) : `${at(start)} – ${at(addDays(start, days - 1))}`
}

/** A task's runs in the window: the task once, its first run and how many (an event carries the task in `data`, with its document in `schedule`). */
export type TaskRow = { key: string, title: string, plugin: string, enabled: boolean, startup: boolean, next: Date|null, runs: number, data: any }

/** Each task once, from the events of the window and the tasks of every document (a task that does not run in the window is listed with no run), in order of first run. */
export function taskRows(events: { start: Date, data?: any }[], schedules: Record<string, { items?: any[] }>, pluginName: (id: string) => string): TaskRow[] {
	const rows = new Map<string, TaskRow>()
	for (const [schedule, doc] of Object.entries(schedules ?? {})) {
		for (const item of doc?.items ?? []) {
			const key = `${schedule}/${item.id}`
			rows.set(key, { key, title: String(item.title ?? ""), plugin: pluginName(String(item.task?.plugin_name ?? "")), enabled: !!item.enabled, startup: item.trigger?.on_startup === true, next: null, runs: 0, data: { ...item, schedule } })
		}
	}
	for (const event of events) {
		const data = event.data
		if (!data) continue
		const row = rows.get(`${data.schedule}/${data.id}`)
		if (!row) continue
		row.runs++
		if (row.next === null || event.start < row.next) row.next = event.start
	}
	const time = (row: TaskRow) => row.next?.getTime() ?? Number.POSITIVE_INFINITY
	return [...rows.values()].sort((a, b) => time(a) - time(b) || a.title.localeCompare(b.title))
}
