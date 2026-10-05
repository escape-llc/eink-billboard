import { describe, expect, it } from "vitest"
import { DateBuilder, MS_PER_DAY, MS_PER_HOUR, MS_PER_MINUTE } from "./DateUtils"

describe("DateUtils constants", () => {
	it("are consistent", () => {
		expect(MS_PER_MINUTE).toBe(60_000)
		expect(MS_PER_HOUR).toBe(60 * MS_PER_MINUTE)
		expect(MS_PER_DAY).toBe(24 * MS_PER_HOUR)
	})
})

describe("DateBuilder", () => {
	// local time on purpose: midnight() is the local midnight
	const start = () => new Date(2026, 9, 5, 13, 45, 30, 123)

	it("midnight() zeroes the time of day and keeps the date", () => {
		const d = new DateBuilder(start()).midnight().date()
		expect([d.getFullYear(), d.getMonth(), d.getDate()]).toEqual([2026, 9, 5])
		expect([d.getHours(), d.getMinutes(), d.getSeconds(), d.getMilliseconds()]).toEqual([0, 0, 0, 0])
	})

	it("adds minutes, hours, and days in milliseconds", () => {
		const base = start()
		expect(new DateBuilder(base).minutes(30).date().getTime() - base.getTime()).toBe(30 * MS_PER_MINUTE)
		expect(new DateBuilder(base).hours(2).date().getTime() - base.getTime()).toBe(2 * MS_PER_HOUR)
		expect(new DateBuilder(base).days(3).date().getTime() - base.getTime()).toBe(3 * MS_PER_DAY)
		expect(new DateBuilder(base).hours(-1).date().getTime() - base.getTime()).toBe(-MS_PER_HOUR)
	})

	it("chains: midnight, then an offset into the day", () => {
		const d = new DateBuilder(start()).midnight().hours(8).minutes(15).date()
		expect([d.getHours(), d.getMinutes()]).toEqual([8, 15])
		expect(d.getDate()).toBe(5)
	})

	it("builds new dates without modifying the one it was given", () => {
		const base = start()
		const before = base.getTime()
		new DateBuilder(base).midnight().days(5).hours(3)
		expect(base.getTime()).toBe(before)
	})
})
