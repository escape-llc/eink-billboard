import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "../components/ApiClient"
import { api } from "../api/client"
import { DEFAULT_TRIGGER, splitTaskErrors, useSchedule } from "./useSchedule"

// the Scheduler's data without the page: the API is a stand-in, and what the page would show as a toast is collected
vi.mock("../api/client", () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() } }))
const mocked = api as unknown as Record<"get" | "post" | "put" | "patch" | "delete", ReturnType<typeof vi.fn>>

const PRIORITY = { id: "priority-update", name: "Priority Update", features: ["layer-priority"], instanceSettings: {} }
const SLIDES = { id: "slide-show", name: "Slide Show", features: ["layer-background"], instanceSettings: {} }
const TASK = { id: "t1", _rev: "r1", title: "Clock", enabled: true, trigger: DEFAULT_TRIGGER, task: { plugin_name: "priority-update", content: { slideMinutes: 5 } } }
const ORPHAN = { ...TASK, id: "t2", _rev: "r2", title: "Gone", task: { plugin_name: "uninstalled", content: {} } }

/** The render answer for a window: two runs of the clock, one of a task whose plugin is gone. */
function render(start = "2026-10-23", days = 7) {
	return {
		success: true, timezone: "America/New_York", start_ts: `${start}T00:00:00-04:00`, days,
		schedules: { "tasks-a": { id: "tasks-a", name: "Timer tasks", items: [TASK, ORPHAN] } },
		render: [
			{ schedule: "tasks-a", id: "t1", scheduled_time: `${start}T09:00:00-04:00` },
			{ schedule: "tasks-a", id: "t1", scheduled_time: `${start}T10:00:00-04:00` },
			{ schedule: "tasks-a", id: "t2", scheduled_time: `${start}T11:00:00-04:00` },
		],
	}
}
function serve(documents = [{ id: "tasks-a", name: "Timer tasks" }]) {
	mocked.get.mockImplementation(async (path: string, options?: { query?: { start?: string, days?: number } }) => {
		if(path === "/api/schedule/tasks/render") return render(options?.query?.start ?? "2026-10-23", options?.query?.days ?? 7)
		if(path === "/api/plugins/list") return [PRIORITY, SLIDES]
		if(path === "/api/datasources/list") return []
		if(path === "/api/schedule/timer/list") return { timed: documents }
		throw new Error(`no route ${path}`)
	})
}
async function started() {
	serve()
	const notices: string[] = []
	const sc = useSchedule((severity, _summary, detail) => notices.push(`${severity}: ${detail}`))
	await sc.start()
	return { sc, notices }
}
const showNone = () => 0

beforeEach(() => { for(const fn of Object.values(mocked)) fn.mockReset() })

describe("the window", () => {
	it("loads a week of runs in the device's zone, each with its task and document", async () => {
		const { sc, notices } = await started()
		expect(sc.loading.value).toBe(false)
		expect([sc.firstDay.value, sc.today.value, sc.dayCount.value, sc.timeZone.value]).toEqual(["2026-10-23", "2026-10-23", 7, "America/New_York"])
		expect(sc.eventList.value.map(e => [e.title, e.duration])).toEqual([["Clock (priority-update)", 5], ["Clock (priority-update)", 5], ["Gone (uninstalled)", 15]])
		expect(sc.eventList.value[0]?.data).toMatchObject({ id: "t1", schedule: "tasks-a" })
		// only the plugins of the timer's layers are offered for a new task
		expect(sc.pluginOptions.value).toEqual([{ id: "priority-update", name: "Priority Update" }])
		expect(notices).toEqual([])
	})

	it("today is the server's; a later window is asked for by its first day", async () => {
		const { sc } = await started()
		expect(mocked.get.mock.calls[0]![1]).toEqual({ query: { days: 7, start: undefined } })
		await sc.move(1)
		expect(sc.offset.value).toBe(7)
		expect(mocked.get.mock.calls.at(-4)![1]).toEqual({ query: { days: 7, start: "2026-10-30" } })
		expect(sc.firstDay.value).toBe("2026-10-30")
		// today stays the day the window was counted from
		expect(sc.today.value).toBe("2026-10-23")
		await sc.goToday()
		expect(sc.offset.value).toBe(0)
		await sc.setMode("day")
		expect(mocked.get.mock.calls.at(-4)![1]).toEqual({ query: { days: 1, start: undefined } })
	})

	it("a schedule that fails to load is a notice, and the page still finishes loading", async () => {
		mocked.get.mockRejectedValue(new Error("down"))
		const notices: string[] = []
		const sc = useSchedule((severity, _summary, detail) => notices.push(`${severity}: ${detail}`))
		await sc.start()
		expect(notices).toEqual(["error: Failed to load the schedule: down"])
		expect(sc.loading.value).toBe(false)
	})

	it("a new day in the device's zone moves the window on; the same day does nothing", async () => {
		const { sc } = await started()
		const calls = mocked.get.mock.calls.length
		await sc.checkDay(new Date())
		// the day the window was loaded on is the browser's day here (the zone's), so nothing is loaded again
		expect(mocked.get.mock.calls.length).toBe(calls)
		await sc.checkDay(new Date(Date.now() + 26 * 3600_000))
		expect(mocked.get.mock.calls.length).toBe(calls + 4)
	})
})

describe("a task in the dialog", () => {
	it("opens a stored task as the editor holds it, with the revision it was loaded at", async () => {
		const { sc } = await started()
		const staged = sc.openTask(sc.eventList.value[0]!.data)
		expect(staged).toEqual({ id: "t1", title: "Clock", enabled: true, trigger: DEFAULT_TRIGGER, plugin_name: "priority-update", content: { slideMinutes: 5 } })
		expect(sc.editTarget.value).toEqual({ schedule: "tasks-a", id: "t1", rev: "r1" })
	})

	it("a task whose plugin is not installed is not opened, and says why", async () => {
		const { sc, notices } = await started()
		expect(sc.openTask(sc.eventList.value[2]!.data)).toBeNull()
		expect(notices).toEqual(["warn: This task uses a plugin that is not installed."])
	})

	it("a new task starts with the first timer plugin in the first document", async () => {
		const { sc } = await started()
		expect(sc.newTask()).toBe(true)
		expect(sc.editModel.value).toEqual({ title: "", enabled: true, trigger: DEFAULT_TRIGGER, plugin_name: "priority-update", content: {} })
		expect(sc.editTarget.value).toEqual({ schedule: "", id: null, rev: undefined })
		expect(sc.newTaskDocument.value).toBe("tasks-a")
	})
})

describe("saving", () => {
	const body = { title: "Clock", enabled: true, trigger: DEFAULT_TRIGGER, task: { plugin_name: "priority-update", content: { slideMinutes: 6 } } }

	it("a stored task is put at its revision", async () => {
		const { sc, notices } = await started()
		sc.openTask(sc.eventList.value[0]!.data)
		mocked.put.mockResolvedValue({})
		expect(await sc.saveTask(body, "r1", showNone)).toBe(true)
		expect(mocked.put.mock.calls[0]).toEqual(["/api/schedule/timer/{doc_id}/items/{item_id}", { path: { doc_id: "tasks-a", item_id: "t1" } }, { ...body, _rev: "r1" }])
		expect(notices).toEqual(["success: Task saved"])
	})

	it("a new task goes into the chosen document, and the first one is made when there is none", async () => {
		serve([])
		const sc = useSchedule(() => {})
		await sc.start()
		sc.newTask()
		mocked.post.mockResolvedValueOnce({ id: "tasks-new" }).mockResolvedValueOnce({})
		expect(await sc.saveTask(body, undefined, showNone)).toBe(true)
		expect(mocked.post.mock.calls[0]).toEqual(["/api/schedule/timer", {}, { name: "Timer tasks" }])
		expect(mocked.post.mock.calls[1]).toEqual(["/api/schedule/timer/{doc_id}/items", { path: { doc_id: "tasks-new" } }, body])
	})

	it("a stale revision is a conflict; Overwrite sends the same task at the server's revision", async () => {
		const { sc } = await started()
		sc.openTask(sc.eventList.value[0]!.data)
		mocked.put.mockRejectedValueOnce(new ApiError(409, "Revision mismatch", { rev: "r9" }))
		expect(await sc.saveTask(body, "r1", showNone)).toBe(false)
		expect(sc.conflict.value).toEqual({ message: "Revision mismatch", rev: "r9" })
		mocked.put.mockResolvedValueOnce({})
		expect(await sc.overwriteTask(showNone)).toBe(true)
		expect(mocked.put.mock.calls[1]![2]).toEqual({ ...body, _rev: "r9" })
		expect(sc.conflict.value).toBeNull()
	})

	it("a 422 shows a plugin field's problem on the field and lists the rest", async () => {
		const { sc } = await started()
		sc.openTask(sc.eventList.value[0]!.data)
		mocked.put.mockRejectedValue(new ApiError(422, "Invalid", { errors: [
			{ path: ["task", "content", "slideMinutes"], message: "Minimum 1" },
			{ path: ["trigger"], message: "Expected a trigger" },
		] }))
		const shown: unknown[] = []
		expect(await sc.saveTask(body, "r1", errors => { shown.push(...errors); return errors.length })).toBe(false)
		expect(shown).toEqual([{ path: ["slideMinutes"], message: "Minimum 1" }])
		expect(sc.serverProblems.value).toEqual(["trigger: Expected a trigger"])
		// a field the form could not show is listed instead of lost
		await sc.saveTask(body, "r1", showNone)
		expect(sc.serverProblems.value).toEqual(["trigger: Expected a trigger", "Invalid"])
	})

	it("Reload takes the server's version of the task; one that cannot be read says so", async () => {
		const { sc, notices } = await started()
		sc.openTask(sc.eventList.value[0]!.data)
		const base = mocked.get.getMockImplementation() as (path: string) => Promise<unknown>
		mocked.get.mockImplementation(async (path: string) => path === "/api/schedule/timer/{doc_id}/items/{item_id}" ? { task: { ...TASK, title: "Theirs", _rev: "r7" } } : base(path))
		expect(await sc.reloadTask()).toBe(true)
		expect(sc.editModel.value.title).toBe("Theirs")
		expect(sc.editTarget.value?.rev).toBe("r7")
		mocked.get.mockRejectedValueOnce(new Error("gone"))
		expect(await sc.reloadTask()).toBe(false)
		expect(notices).toEqual(["error: Failed to reload the task: gone"])
	})

	it("a delete names the revision; a stale one is a conflict", async () => {
		const { sc } = await started()
		sc.openTask(sc.eventList.value[0]!.data)
		mocked.delete.mockResolvedValueOnce({})
		expect(await sc.deleteTask()).toBe("done")
		expect(mocked.delete.mock.calls[0]).toEqual(["/api/schedule/timer/{doc_id}/items/{item_id}", { path: { doc_id: "tasks-a", item_id: "t1" }, query: { rev: "r1" } }])
		mocked.delete.mockRejectedValueOnce(new ApiError(409, "Revision mismatch"))
		expect(await sc.deleteTask()).toBe("conflict")
		expect(sc.conflict.value?.message).toMatch(/reload it before deleting/)
		mocked.delete.mockRejectedValueOnce(new Error("offline"))
		expect(await sc.deleteTask()).toBe("failed")
	})
})

describe("helpers", () => {
	it("a problem outside the plugin's content is listed with its path", () => {
		expect(splitTaskErrors([{ path: ["title"], message: "Required" }, {}])).toEqual({ onField: [], listed: ["title: Required", ""] })
	})
})
