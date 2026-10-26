import { describe, expect, it } from "vitest"
import { cleanTrigger, isOnDemand, TriggerDefSchema, TriggerSchema } from "./ScheduleDefs"

const valid = () => ({
	on_startup: false,
	day: { type: "dayofweek", days: [0, 1, 2, 3, 4, 5, 6] },
	time: { type: "hourly", minutes: [0, 15, 30, 45] },
})

/** The paths ("day.days") of the validation problems of a trigger. */
function problems(trigger: unknown): string[] {
	const result = TriggerDefSchema.safeParse(trigger)
	return result.success ? [] : result.error.issues.map(i => i.path.join("."))
}

describe("TriggerDefSchema", () => {
	it("accepts the trigger shapes the timer tasks use", () => {
		expect(TriggerDefSchema.safeParse(valid()).success).toBe(true)
		expect(TriggerDefSchema.safeParse({
			on_startup: true,
			day: { type: "dayofmonth", days: [1, 15] },
			time: { type: "hourofday", hours: [8, 20], minutes: [0] },
		}).success).toBe(true)
		expect(TriggerDefSchema.safeParse({
			on_startup: false,
			day: { type: "dayandmonth", month: 12, day: 25 },
			time: { type: "specific", hour: 7, minute: 30 },
		}).success).toBe(true)
	})

	it("requires at least one day for the day-of-week and day-of-month types", () => {
		for (const type of ["dayofweek", "dayofmonth"]) {
			expect(problems({ ...valid(), day: { type } })).toEqual(["day.days"])
			expect(problems({ ...valid(), day: { type, days: [] } })).toEqual(["day.days"])
		}
	})

	it("requires both the month and the day for a day-and-month trigger", () => {
		expect(problems({ ...valid(), day: { type: "dayandmonth" } }).sort()).toEqual(["day.day", "day.month"])
		expect(problems({ ...valid(), day: { type: "dayandmonth", month: 1 } })).toEqual(["day.day"])
		// month 0 and day 0 are values, not missing
		expect(problems({ ...valid(), day: { type: "dayandmonth", month: 0, day: 0 } })).toEqual([])
	})

	it("requires minutes for hourly, and hours plus minutes for hour-of-day", () => {
		expect(problems({ ...valid(), time: { type: "hourly" } })).toEqual(["time.minutes"])
		expect(problems({ ...valid(), time: { type: "hourly", minutes: [] } })).toEqual(["time.minutes"])
		expect(problems({ ...valid(), time: { type: "hourofday" } }).sort()).toEqual(["time.hours", "time.minutes"])
		expect(problems({ ...valid(), time: { type: "hourofday", hours: [9] } })).toEqual(["time.minutes"])
	})

	it("requires the hour and the minute for a specific time, accepting midnight", () => {
		expect(problems({ ...valid(), time: { type: "specific" } }).sort()).toEqual(["time.hour", "time.minute"])
		expect(problems({ ...valid(), time: { type: "specific", hour: 0, minute: 0 } })).toEqual([])
	})

	it("rejects unknown trigger types", () => {
		expect(problems({ ...valid(), day: { type: "fortnightly" } })).toEqual(["day.type"])
		expect(problems({ ...valid(), time: { type: "whenever" } })).toEqual(["time.type"])
	})

	it("requires on_startup and rejects wrongly typed fields", () => {
		const { on_startup: _omitted, ...rest } = valid()
		expect(problems(rest)).toContain("on_startup")
		expect(problems({ ...valid(), day: { type: "dayofweek", days: ["monday"] } })).not.toEqual([])
	})
})

describe("a task that runs on demand", () => {
	it("has nothing to check", () => {
		expect(isOnDemand({ on_demand: true })).toBe(true)
		expect(isOnDemand({ on_demand: false })).toBe(false)
		expect(isOnDemand(undefined)).toBe(false)
		expect(TriggerSchema.safeParse({ on_demand: true }).success).toBe(true)
	})
	it("leaves a timed trigger's problems at their paths", () => {
		expect(TriggerSchema.safeParse(valid()).success).toBe(true)
		const result = TriggerSchema.safeParse({ ...valid(), day: { type: "dayofweek", days: [] } })
		expect(result.success ? [] : result.error.issues.map(i => i.path.join("."))).toEqual(["day.days"])
	})
})

describe("the trigger that is saved", () => {
	it("keeps only the keys of its kind", () => {
		expect(cleanTrigger({ on_demand: true, on_startup: false, day: { type: "dayofweek", days: [1] }, time: { type: "hourly", minutes: [0] } })).toEqual({ on_demand: true })
		expect(cleanTrigger({ ...valid(), on_demand: false })).toEqual(valid())
		expect(cleanTrigger(valid())).toEqual(valid())
	})
})
