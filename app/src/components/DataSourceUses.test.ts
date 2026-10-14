import { describe, expect, it } from "vitest"
import { missingUses } from "./DataSourceUses"

describe("the data sources a source uses", () => {
	const available = [{ id: "weather" }, { id: "calendar" }]
	it("names the ones the device does not have", () => {
		expect(missingUses(["weather"], available)).toEqual([])
		expect(missingUses(["weather", "reminders", "ai"], available)).toEqual(["reminders", "ai"])
	})
	it("has none to miss when the source uses nothing", () => {
		expect(missingUses(undefined, available)).toEqual([])
		expect(missingUses([], [])).toEqual([])
	})
})
