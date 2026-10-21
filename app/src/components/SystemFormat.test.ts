import { describe, expect, it } from "vitest"
import { deviceMoment, failedCalls, formatBytes, formatShare, formatUptime, gaugeSeverity, statusSummary, temperatureSeverity } from "./SystemFormat"

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

describe("API usage", () => {
	it("counts a call as failed when there was no answer or the status is 400 or more", () => {
		expect(failedCalls({ "200": 40, "304": 3, "404": 2, "429": 1, "timeout": 4, "tls": 1 })).toBe(8)
		expect(failedCalls({})).toBe(0)
		expect(failedCalls(undefined)).toBe(0)
	})
	it("lists the statuses, the most common first", () => {
		expect(statusSummary({ "429": 2, "200": 40, "500": 2, "timeout": 1 })).toBe("200 × 40, 429 × 2, 500 × 2, timeout × 1")
		expect(statusSummary(undefined)).toBe("")
	})
	it("shows a share as a percentage and nothing counted as a dash", () => {
		expect(formatShare(0.857)).toBe("86%")
		expect(formatShare(0)).toBe("0%")
		expect(formatShare(null)).toBe("–")
	})
	it("reads the device's wall clock as the server wrote it, whatever zone the browser is in", () => {
		expect(deviceMoment("2026-10-21T12:17:09.5+02:00")).toBe("2026-10-21 12:17")
		expect(deviceMoment("2026-10-21T23:59:00-07:00")).toBe("2026-10-21 23:59")
		expect(deviceMoment(null)).toBe("")
		expect(deviceMoment("yesterday")).toBe("")
	})
})
