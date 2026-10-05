import { describe, expect, it } from "vitest"
import { dateToIso, isoToDate } from "./FormDates"

describe("FormDates", () => {
	it("round-trips a date without shifting the day (no time zone drift)", () => {
		for (const iso of ["2026-01-01", "2026-03-08", "2026-11-01", "2026-12-31", "2028-02-29"]) {
			expect(dateToIso(isoToDate(iso))).toBe(iso)
		}
	})
	it("rejects empty, malformed and impossible dates", () => {
		for (const bad of [null, undefined, "", "2026-1-1", "2026-02-31", "2026-13-01", 20260101, "2026-01-01T00:00"]) {
			expect(isoToDate(bad)).toBeNull()
		}
	})
	it("returns null for no date", () => {
		expect(dateToIso(null)).toBeNull()
		expect(dateToIso(undefined)).toBeNull()
	})
})
