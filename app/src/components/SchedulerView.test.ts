import { describe, expect, it } from "vitest"
import { daysOf, rangeLabel, step, switchMode, taskRows, triggerText, windowOf } from "./SchedulerView"

describe("the scheduler's window", () => {
	it("is a day or a week from the offset, starting on today's weekday", () => {
		expect(windowOf("day", "2026-10-13", 0)).toEqual({ start: "2026-10-13", days: 1 })
		expect(windowOf("week", "2026-10-13", 7)).toEqual({ start: "2026-10-20", days: 7 })
		expect(windowOf("list", "2026-10-13", 0)).toEqual({ start: "2026-10-13", days: 7 })
		expect([daysOf("day"), daysOf("week"), daysOf("list")]).toEqual([1, 7, 7])
	})
	it("moves a day or a week, and never before today", () => {
		expect(step("day", 0, 1)).toBe(1)
		expect(step("week", 0, 1)).toBe(7)
		expect(step("week", 7, -1)).toBe(0)
		expect(step("day", 0, -1)).toBe(0)
		expect(step("week", 3, -1)).toBe(0)
		expect(windowOf("day", "2026-10-13", -5).start).toBe("2026-10-13")
	})
	it("keeps the week on today's weekday when the mode changes", () => {
		expect(switchMode("week", 10)).toBe(7)
		expect(switchMode("list", 13)).toBe(7)
		expect(switchMode("day", 10)).toBe(10)
		expect(switchMode("week", 6)).toBe(0)
	})
	it("names the days shown, across a month", () => {
		expect(rangeLabel("2026-10-13", 1)).toBe("Tue Oct 13")
		expect(rangeLabel("2026-10-27", 7)).toBe("Tue Oct 27 – Mon Nov 2")
	})
})

describe("the list of tasks", () => {
	const schedules = { doc: { items: [
		{ id: "a", title: "Clock", enabled: true, trigger: { on_startup: true, day: { type: "dayofweek" }, time: { type: "hourly" } }, task: { plugin_name: "overlay" } },
		{ id: "b", title: "Poem", enabled: true, trigger: { on_startup: false }, task: { plugin_name: "interstitial" } },
		{ id: "c", title: "Off", enabled: false, task: { plugin_name: "overlay" } },
	] } }
	const at = (h: number) => new Date(Date.UTC(2026, 9, 13, h))
	const events = [
		{ start: at(12), data: { schedule: "doc", id: "a" } },
		{ start: at(9), data: { schedule: "doc", id: "b" } },
		{ start: at(10), data: { schedule: "doc", id: "a" } },
		{ start: at(11), data: undefined },
	]
	it("has each task once, with its first run and how many, in order of first run", () => {
		const rows = taskRows(events, schedules, id => ({ overlay: "Overlay", interstitial: "Priority Update" })[id] ?? id, at(0))
		expect(rows.map(r => [r.title, r.plugin, r.runs, r.next?.getUTCHours() ?? null, r.enabled, r.startup])).toEqual([
			["Poem", "Priority Update", 1, 9, true, false],
			["Clock", "Overlay", 2, 10, true, true],
			["Off", "Overlay", 0, null, false, false],
		])
		// the row opens the task in its document
		expect(rows[0]!.data).toMatchObject({ id: "b", schedule: "doc" })
	})
	it("names the trigger as the editor does, and the next run is the first one from now on", () => {
		const rows = taskRows(events, schedules, id => id, at(10))
		const clock = rows.find(r => r.title === "Clock")!
		expect(clock.trigger).toBe("Day-of-Week/Hourly")
		// the 09:00 and 10:00 runs have passed (a window starts at midnight); all of its runs are still counted
		expect([clock.next?.getUTCHours(), clock.runs]).toEqual([10, 2])
		expect(rows.find(r => r.title === "Poem")!.next).toBeNull()
		expect(taskRows(events, schedules, id => id, at(11)).find(r => r.title === "Clock")!.next?.getUTCHours()).toBe(12)
		expect(triggerText({ day: { type: "dayofmonth" }, time: { type: "hourofday" } })).toBe("Day-of-Month/Hour-of-Day")
		expect(triggerText(undefined)).toBe("")
	})
	it("is empty without documents", () => {
		expect(taskRows([], {}, id => id)).toEqual([])
	})
})
