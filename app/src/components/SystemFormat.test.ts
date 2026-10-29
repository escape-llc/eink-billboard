import { describe, expect, it } from "vitest"
import { devicePills, machinePills, periodPills, piPills, sizePills, deviceMoment, failedCalls, fanText, formatBytes, formatShare, formatUptime, gaugeSeverity, quotaLine, quotaSeverity, quotaWarning, answerKind, answerPills, usagePills, storageLine, storagePills, temperatureSeverity } from "./SystemFormat"

describe("sizes", () => {
	it("are in the largest unit that keeps them readable", () => {
		expect(formatBytes(0)).toBe("0 b")
		expect(formatBytes(1000)).toBe("1000 b")
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
	it("lists the statuses by code, then the calls with no answer, each titled with what it means", () => {
		expect(answerPills({ "timeout": 1, "404": 48, "500": 2, "200": 7, "304": 6, "299": 1 })).toEqual([
			{ code: "200", count: 7, kind: "success", title: "200 OK: 7 calls" },
			{ code: "299", count: 1, kind: "success", title: "299: 1 call" },
			{ code: "304", count: 6, kind: "info", title: "304 Not Modified: 6 calls" },
			{ code: "404", count: 48, kind: "warn", title: "404 Not Found: 48 calls" },
			{ code: "500", count: 2, kind: "danger", title: "500 Internal Server Error: 2 calls" },
			{ code: "timeout", count: 1, kind: "danger", title: "1 call: no answer in time" }])
		expect(answerPills(undefined)).toEqual([])
	})
	it("are toned by what the answer means", () => {
		expect(["200", "204", "301", "304", "404", "429", "500", "503", "timeout", "tls", "100"].map(answerKind))
			.toEqual(["success", "success", "info", "info", "warn", "warn", "danger", "danger", "danger", "danger", "info"])
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

describe("the fan", () => {
	it("is off only when it is not driven", () => {
		expect(fanText(0, 0)).toBe("Off")
		expect(fanText(0, undefined)).toBe("Off")
		// the Pi 5's first step (75 of 255) on a fan that reports no speed
		expect(fanText(0, 29)).toBe("29% power, no speed reported")
		expect(fanText(3120, 40)).toBe("3120 rpm (40% power)")
		expect(fanText(3120, undefined)).toBe("3120 rpm")
	})
})

describe("an API data source's quota", () => {
	it("is a colour and a warning in words from 80 percent, and at the quota", () => {
		expect([quotaSeverity(79.9), quotaSeverity(80), quotaSeverity(99.9), quotaSeverity(100), quotaSeverity(130), quotaSeverity(undefined)]).toEqual(["success", "warn", "warn", "danger", "danger", "success"])
		expect([quotaWarning(50), quotaWarning(80), quotaWarning(100), quotaWarning(null)]).toEqual(["", "Over 80% of the quota is used", "The quota is used up", ""])
	})
	it("says this period's calls with its first day and the next reset", () => {
		expect(quotaLine({ limit: 1000, used: 620, percent: 62, since: "2026-10-05", resets: "2026-11-05" })).toBe("620 of 1000 calls since Oct 5 (62%), resets Nov 5")
		expect(quotaLine({ limit: 3, used: 0, percent: 0, since: "2026-12-01", resets: "2027-01-01" })).toBe("0 of 3 calls since Dec 1 (0%), resets Jan 1")
	})
})

describe("the closed cards' lines", () => {
	it("say an API data source's month in one line", () => {
		const pairs = (pills: { label: string, value: string, kind: string }[]) => pills.map(p => `${p.label} ${p.value} ${p.kind}`)
		expect(pairs(usagePills({ calls: 70, status: { "200": 68, "429": 2 }, hitRate: 0.75 }))).toEqual(["calls 70 neutral", "failed 2 danger", "cache 75% neutral"])
		// nothing failed and no cache lookups: only the calls
		expect(pairs(usagePills({ calls: 1, status: { "200": 1 }, hitRate: null }))).toEqual(["calls 1 neutral"])
		// a plan adds its share, toned by how much is used
		expect(pairs(usagePills({ calls: 25 }, { percent: 25, limit: 100, used: 25 })).pop()).toBe("quota 25% success")
		expect(pairs(usagePills({ calls: 90 }, { percent: 90, limit: 100, used: 90 })).pop()).toBe("quota 90% warn")
		expect(pairs(usagePills({ calls: 100 }, { percent: 100, limit: 100, used: 100 })).pop()).toBe("quota 100% danger")
	})
	it("add the storage up, with its share of the disk", () => {
		const areas = [{ files: 100, bytes: 1024 * 1024 * 10 }, { files: 40, bytes: 1024 * 1024 * 2 }]
		expect(storageLine(areas, { total: 1024 * 1024 * 1200 })).toBe("12 MB in 140 files, 1% of the disk")
		expect(storageLine(areas, { total: 1024 ** 4 })).toBe("12 MB in 140 files, less than 0.1% of the disk")
		expect(storageLine([{ files: 1, bytes: 10 }], null)).toBe("10 b in 1 file")
	})
	it("are pills for the closed card, the free space toned by how full the disk is", () => {
		const areas = [{ files: 100, bytes: 1024 * 1024 * 8 }, { files: 40, bytes: 1024 * 1024 * 4 }]
		const pills = (volume: { total: number, free: number, percent: number } | null) => storagePills(areas, volume).map(p => `${p.label} ${p.value} ${p.kind}`)
		expect(pills({ total: 1024 ** 4, free: 1024 ** 4 / 2, percent: 50 })).toEqual(["size 12 MB neutral", "files 140 neutral", "disk <0.1% neutral", "free 512 GB success"])
		expect(pills({ total: 1024 * 1024 * 1200, free: 1024 * 1024 * 60, percent: 95 })).toEqual(["size 12 MB neutral", "files 140 neutral", "disk 1% neutral", "free 60 MB danger"])
		expect(pills(null)).toEqual(["size 12 MB neutral", "files 140 neutral"])
	})
})

describe("the cards' pills (#796)", () => {
	const pairs = (pills: { label: string, value: string, kind: string }[]) => pills.map(p => `${p.label} ${p.value} ${p.kind}`)
	it("show each part of the device on the tone of its state, with what it said in the title", () => {
		const pills = devicePills({ "display": { state: "ok", message: "Running." }, "timer-layer": { state: "failed", message: "Broken." }, "playlist-layer": { state: "starting", message: "Starting." } }, { "display": "Display", "timer-layer": "Timer tasks" })
		expect(pairs(pills)).toEqual(["Display running success", "Timer tasks failed danger", "playlist-layer starting info"])
		expect(pills.map(p => p.icon)).toEqual(["tv", "schedule", "playlist_play"])
		expect(pills[1].title).toBe("Timer tasks: Broken.")
		// the memory the application uses is the Application row's, when the machine can say
		const withMemory = devicePills({ "display": { state: "ok", message: "Running." } }, { "display": "Display" }, 120 * 1024 ** 2)
		expect(pairs(withMemory)).toEqual(["Display running success", "memory 120 MB neutral"])
		expect([withMemory[1].title, withMemory[1].icon]).toEqual(["The memory the application uses", "memory_alt"])
		// and what it keeps on disk in all: the Storage card's size pill
		const withStorage = devicePills({}, {}, null, [{ files: 100, bytes: 1024 * 1024 * 8 }, { files: 40, bytes: 1024 * 1024 * 4 }])
		expect(pairs(withStorage)).toEqual(["size 12 MB neutral"])
		expect([withStorage[0].icon, withStorage[0].title]).toEqual(["database", "What the device keeps, in all: 12 MB in 140 files"])
	})
	it("show the machine, leaving out what it cannot read, with memory and disk toned by how full they are", () => {
		const host = { os: "Linux", os_release: "6.12", machine: "aarch64", python: "3.13.7", cpus: 4, commit: "abc1234", uptime_seconds: 3 * 86400, app_uptime_seconds: 30, clock: "unsynced" as const }
		const load = { cpu_percent: 12, load: [0.5, 0.4, 0.3], memory: { total: 8 * 1024 ** 3, used: 7.4 * 1024 ** 3, percent: 92 }, app_memory: 120 * 1024 ** 2 }
		const pills = machinePills(host, load, { total: 100 * 1024 ** 3, free: 40 * 1024 ** 3, percent: 60 }, "abc1234", false)
		expect(pairs(pills)).toEqual(["system Linux 6.12 neutral", "build abc1234 neutral", "python 3.13.7 neutral", "up 3 days 0 h neutral", "app 30 s neutral", "clock not set warn",
			"processor 4 cores · 12% neutral", "memory 7.4 GB / 8 GB danger", "disk 40 GB free success"])
		expect(pills.find(p => p.label === "processor")?.title).toBe("4 cores, 12% busy (load 0.5 0.4 0.3)")
		const bare = machinePills({ ...host, uptime_seconds: null, app_uptime_seconds: null, clock: null }, {}, null, "def5678", true)
		expect(pairs(bare)).toEqual(["system Linux 6.12 neutral", "build abc1234 / def5678 warn", "python 3.13.7 neutral", "processor 4 cores neutral"])
		expect(bare[1].title).toContain("Reload the page")
	})
	it("show a Pi's temperature and power on their tones", () => {
		expect(pairs(piPills({ model: "Raspberry Pi 5", temperature_c: 82, cpu_mhz: 1500, cpu_max_mhz: 2400, fan_rpm: 2100, throttled: [] })))
			.toEqual(["model Raspberry Pi 5 neutral", "temperature 82 °C danger", "speed 1500 MHz neutral", "fan 2100 rpm neutral", "power ok success"])
		expect(pairs(piPills({ model: "Pi", throttled: ["Under-voltage now", "Throttled since start"] })))
			.toEqual(["model Pi neutral", "power Under-voltage now danger", "power Throttled since start warn"])
	})
	it("show a size per name, with the files and what is kept in the title", () => {
		const [pill] = sizePills([{ name: "rss", files: 3, bytes: 2048, kept: 1024 }])
		expect(pairs([pill])).toEqual(["rss 2 KB neutral"])
		expect(pill.title).toBe("rss: 2 KB in 3 files, 1 KB of it kept (can be fetched again)")
	})
	it("show a period of calls, the failed ones only when some failed", () => {
		const period = { calls: 20, status: { "200": 19, "429": 1 }, sent: 2400, received: 40960, hitRate: 0.75, bytesSaved: 6000 }
		expect(pairs(periodPills("7 days", period))).toEqual(["calls 20 neutral", "failed 1 danger", "sent 2.3 KB neutral", "received 40 KB neutral", "cache 75% neutral"])
		expect(pairs(periodPills("Today", { calls: 4, status: { "200": 4 }, sent: 0, received: 0 }))).toEqual(["calls 4 neutral", "sent 0 b neutral", "received 0 b neutral"])
	})
})
