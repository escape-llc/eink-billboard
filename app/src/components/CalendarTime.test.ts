import { describe, expect, it } from "vitest"
import { addDays, browserZoneDifference, dayInfo, daysFrom, place, segments, slotCount, timeSlots, zonedParts } from "./CalendarTime"

const WHOLE_DAY = { start: 0, end: 1440, interval: 30 }

describe("zonedParts", () => {
	it("reads the day and minute in the given zone, not the machine's", () => {
		const instant = new Date("2026-11-03T14:00:00Z")
		expect(zonedParts(instant, "America/New_York")).toEqual({ key: "2026-11-03", minutes: 9 * 60 })
		expect(zonedParts(instant, "Asia/Kolkata")).toEqual({ key: "2026-11-03", minutes: 19 * 60 + 30 })
		expect(zonedParts(instant, "Pacific/Auckland")).toEqual({ key: "2026-11-04", minutes: 3 * 60 })
	})
	it("never says 24 at midnight", () => {
		expect(zonedParts(new Date("2026-11-03T05:00:00Z"), "America/New_York")).toEqual({ key: "2026-11-03", minutes: 0 })
	})
	it("takes a fixed offset as a zone, and an unknown name as the browser's", () => {
		expect(zonedParts(new Date("2026-01-01T00:00:00Z"), "+05:30")).toEqual({ key: "2026-01-01", minutes: 5 * 60 + 30 })
		expect(() => zonedParts(new Date(), "Not/AZone")).not.toThrow()
	})
	it("is the same for the hour after the clocks go back (the repeated hour is not skipped)", () => {
		expect(zonedParts(new Date("2026-11-01T05:30:00Z"), "America/New_York")).toEqual({ key: "2026-11-01", minutes: 60 + 30 })
		expect(zonedParts(new Date("2026-11-01T06:30:00Z"), "America/New_York")).toEqual({ key: "2026-11-01", minutes: 60 + 30 })
	})
})

describe("days", () => {
	it("a week across the end of daylight-saving time is seven different days", () => {
		expect(daysFrom("2026-10-30", 7)).toEqual(["2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"])
	})
	it("a week across the start of daylight-saving time, month and year ends, leap days", () => {
		expect(daysFrom("2026-03-07", 3)).toEqual(["2026-03-07", "2026-03-08", "2026-03-09"])
		expect(addDays("2026-12-31", 1)).toBe("2027-01-01")
		expect(addDays("2028-02-28", 1)).toBe("2028-02-29")
		expect(addDays("2026-03-01", -1)).toBe("2026-02-28")
	})
	it("gives the weekday (0 = Sunday) and day of month of a calendar day", () => {
		const day = dayInfo("2026-11-01")
		expect([day.weekday, day.dayOfMonth, day.date.getDate(), day.date.getDay()]).toEqual([0, 1, 1, 0])
	})
})

describe("slots and placement", () => {
	it("an event is in the slot its start falls in, not the nearest one", () => {
		const rowOf = (minutes: number) => place({ start: minutes, length: 15 }, WHOLE_DAY)!.row
		expect(rowOf(8 * 60)).toBe(17)
		expect(rowOf(8 * 60 + 14)).toBe(17)
		expect(rowOf(8 * 60 + 15)).toBe(17)
		expect(rowOf(8 * 60 + 29)).toBe(17)
		expect(rowOf(8 * 60 + 45)).toBe(18)
	})
	it("it covers as many rows as it lasts, and one at least", () => {
		expect(place({ start: 480, length: 90 }, WHOLE_DAY)).toEqual({ row: 17, span: 3 })
		expect(place({ start: 480, length: 1 }, WHOLE_DAY)).toEqual({ row: 17, span: 1 })
		// 08:45 + 30 minutes touches two slots
		expect(place({ start: 8 * 60 + 45, length: 30 }, WHOLE_DAY)).toEqual({ row: 18, span: 2 })
	})
	it("the rows count from the first shown time, and what is outside it is not placed", () => {
		const day = { start: 8 * 60, end: 18 * 60, interval: 60 }
		expect(slotCount(day)).toBe(10)
		expect(timeSlots(day).map(s => s.hour)).toEqual([8, 9, 10, 11, 12, 13, 14, 15, 16, 17])
		expect(place({ start: 9 * 60, length: 30 }, day)).toEqual({ row: 2, span: 1 })
		expect(place({ start: 6 * 60, length: 30 }, day)).toBeNull()
		expect(place({ start: 18 * 60, length: 30 }, day)).toBeNull()
		// partly before the start: the visible part from the first row
		expect(place({ start: 7 * 60 + 30, length: 90 }, day)).toEqual({ row: 1, span: 1 })
	})
	it("an event at the end of the day does not run past the last row", () => {
		expect(place({ start: 23 * 60 + 45, length: 120 }, WHOLE_DAY)).toEqual({ row: 48, span: 1 })
	})
	it("the labels are whole minutes of the day: no zone is involved", () => {
		const slots = timeSlots({ start: 0, end: 120, interval: 30 })
		expect(slots.map(s => `${String(s.hour).padStart(2, "0")}:${String(s.minute).padStart(2, "0")}`)).toEqual(["00:00", "00:30", "01:00", "01:30"])
		expect(slots.map(s => s.row)).toEqual([1, 2, 3, 4])
	})
})

describe("an event across midnight", () => {
	it("is drawn on both days", () => {
		expect(segments("2026-11-03", 23 * 60 + 30, 90)).toEqual([
			{ day: "2026-11-03", start: 1410, length: 30, continued: false },
			{ day: "2026-11-04", start: 0, length: 60, continued: true }
		])
	})
	it("stays on one day when it fits, and lasts at least a minute", () => {
		expect(segments("2026-11-03", 600, 15)).toEqual([{ day: "2026-11-03", start: 600, length: 15, continued: false }])
		expect(segments("2026-11-03", 600, 0)[0]!.length).toBe(1)
	})
	it("is cut off after a sane number of days", () => {
		expect(segments("2026-11-03", 0, 1440 * 200)).toHaveLength(62)
	})
})

describe("browserZoneDifference", () => {
	const instant = new Date("2026-11-03T14:00:00Z")
	it("says nothing when the zones agree or the device's zone is unknown", () => {
		expect(browserZoneDifference("America/New_York", instant, "America/New_York")).toBeNull()
		expect(browserZoneDifference("America/Toronto", instant, "America/New_York")).toBeNull()
		expect(browserZoneDifference(undefined, instant, "Asia/Kolkata")).toBeNull()
	})
	it("says how far ahead or behind the browser is, in hours and minutes", () => {
		expect(browserZoneDifference("America/New_York", instant, "Europe/Berlin")).toBe("6 h ahead")
		expect(browserZoneDifference("Europe/Berlin", instant, "America/New_York")).toBe("6 h behind")
		expect(browserZoneDifference("America/New_York", instant, "Asia/Kolkata")).toBe("10 h 30 min ahead")
	})
	it("uses the offsets in force at that moment (daylight-saving differs between hemispheres)", () => {
		// 2026-07-01: New York is UTC-4, Sydney UTC+10
		expect(browserZoneDifference("America/New_York", new Date("2026-07-01T00:00:00Z"), "Australia/Sydney")).toBe("14 h ahead")
		// 2026-11-03: New York is UTC-5, Sydney UTC+11
		expect(browserZoneDifference("America/New_York", instant, "Australia/Sydney")).toBe("16 h ahead")
	})
})
