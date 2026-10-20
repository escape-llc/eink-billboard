import { describe, expect, it } from "vitest"
import { formatBytes, formatUptime, gaugeSeverity, temperatureSeverity } from "./SystemFormat"

describe("sizes", () => {
	it("are in the largest unit that keeps them readable", () => {
		expect(formatBytes(0)).toBe("0 bytes")
		expect(formatBytes(1000)).toBe("1000 bytes")
		expect(formatBytes(1536)).toBe("1.5 KB")
		expect(formatBytes(2 * 1024)).toBe("2 KB")
		expect(formatBytes(38 * 1024 * 1024)).toBe("38 MB")
		expect(formatBytes(5.5 * 1024 ** 3)).toBe("5.5 GB")
	})
	it("are a question mark when there is no number", () => {
		for (const bad of [undefined, null, -1, Number.NaN, Infinity]) expect(formatBytes(bad as number)).toBe("?")
	})
})

describe("uptime", () => {
	it("is the two largest units", () => {
		expect(formatUptime(30)).toBe("30 s")
		expect(formatUptime(45 * 60 + 10)).toBe("45 min")
		expect(formatUptime(2 * 3600 + 5 * 60)).toBe("2 h 5 min")
		expect(formatUptime(86400 + 4 * 3600)).toBe("1 day 4 h")
		expect(formatUptime(3 * 86400 + 4 * 3600)).toBe("3 days 4 h")
		expect(formatUptime(undefined)).toBe("?")
	})
})

describe("gauges", () => {
	it("warn from 75 percent and fail from 90", () => {
		expect(gaugeSeverity(10)).toBe("success")
		expect(gaugeSeverity(75)).toBe("warn")
		expect(gaugeSeverity(90)).toBe("danger")
		expect(gaugeSeverity(undefined)).toBe("success")
	})
	it("treat a hot Pi as the firmware does", () => {
		expect(temperatureSeverity(55)).toBe("success")
		expect(temperatureSeverity(72)).toBe("warn")
		expect(temperatureSeverity(81)).toBe("danger")
	})
})
