import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "../components/ApiClient"
import { api } from "../api/client"
import { inApp } from "../api/inApp"
import { changedEvent, fakeLink, settle } from "../api/fakeLink"
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
	const sc = inApp(() => useSchedule((severity, _summary, detail) => notices.push(`${severity}: ${detail}`)))
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
		const lastWindow = () => mocked.get.mock.calls.filter(c => c[0] === "/api/schedule/tasks/render").at(-1)![1]
		expect(lastWindow()).toEqual({ query: { days: 7, start: undefined } })
		await sc.move(1)
		expect(sc.offset.value).toBe(7)
		expect(lastWindow()).toEqual({ query: { days: 7, start: "2026-10-30" } })
		expect(sc.firstDay.value).toBe("2026-10-30")
		// today stays the day the window was counted from
		expect(sc.today.value).toBe("2026-10-23")
		await sc.goToday()
		expect(sc.offset.value).toBe(0)
		await sc.setMode("day")
		expect(lastWindow()).toEqual({ query: { days: 1, start: undefined } })
	})

	it("a schedule that fails to load is a notice, and the page still finishes loading", async () => {
		mocked.get.mockRejectedValue(new Error("down"))
		const notices: string[] = []
		const sc = inApp(() => useSchedule((severity, _summary, detail) => notices.push(`${severity}: ${detail}`)))
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
		// the timeline and the documents again; what is installed is the cache's, still fresh
		expect(mocked.get.mock.calls.map(c => c[0]).slice(calls)).toEqual(["/api/schedule/tasks/render", "/api/schedule/timer/list"])
	})
})

describe("a task in the dialog", () => {
	it("opens a stored task as the editor holds it, with the revision it was loaded at", async () => {
		const { sc } = await started()
		const staged = sc.openTask(sc.eventList.value[0]!.data)
		expect(staged).toEqual({ id: "t1", title: "Clock", enabled: true, trigger: DEFAULT_TRIGGER, plugin_name: "priority-update", content: { slideMinutes: 5 } })
		expect(sc.editTarget.value).toEqual({ schedule: "tasks-a", id: "t1" })
		// shown, it is the editor's at that revision
		sc.showTask(staged!)
		expect(sc.taskRev.value).toBe("r1")
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
		expect(sc.editTarget.value).toEqual({ schedule: "", id: null })
		expect(sc.newTaskDocument.value).toBe("tasks-a")
	})
})

// what the page does: open a stored task, show it, and the form reports its values
function opened(sc: ReturnType<typeof useSchedule>, index = 0) {
	const staged = sc.openTask(sc.eventList.value[index]!.data)!
	sc.showTask(staged)
	sc.values(staged, true)
	return staged
}

describe("saving", () => {
	const body = { title: "Clock", enabled: true, trigger: DEFAULT_TRIGGER, task: { plugin_name: "priority-update", content: { slideMinutes: 6 } } }

	it("a stored task is put at its revision", async () => {
		const { sc, notices } = await started()
		opened(sc)
		mocked.put.mockResolvedValue({})
		expect(await sc.saveTask(body, showNone)).toBe(true)
		expect(mocked.put.mock.calls[0]).toEqual(["/api/schedule/timer/{doc_id}/items/{item_id}", { path: { doc_id: "tasks-a", item_id: "t1" } }, { ...body, _rev: "r1" }])
		expect(notices).toEqual(["success: Task saved"])
	})

	it("a new task goes into the chosen document, and the first one is made when there is none", async () => {
		serve([])
		const sc = inApp(() => useSchedule(() => {}))
		await sc.start()
		sc.newTask()
		sc.values(sc.editModel.value, true)
		mocked.post.mockResolvedValueOnce({ id: "tasks-new" }).mockResolvedValueOnce({})
		expect(await sc.saveTask(body, showNone)).toBe(true)
		expect(mocked.post.mock.calls[0]).toEqual(["/api/schedule/timer", {}, { name: "Timer tasks" }])
		expect(mocked.post.mock.calls[1]).toEqual(["/api/schedule/timer/{doc_id}/items", { path: { doc_id: "tasks-new" } }, body])
	})

	it("a stale revision is a conflict; Overwrite sends the same task at the server's revision", async () => {
		const { sc } = await started()
		opened(sc)
		mocked.put.mockRejectedValueOnce(new ApiError(409, "Revision mismatch", { rev: "r9" }))
		expect(await sc.saveTask(body, showNone)).toBe(false)
		expect(sc.conflict.value).toEqual({ message: "Revision mismatch", rev: "r9" })
		mocked.put.mockResolvedValueOnce({})
		expect(await sc.overwriteTask(showNone)).toBe(true)
		expect(mocked.put.mock.calls[1]![2]).toEqual({ ...body, _rev: "r9" })
		expect(sc.conflict.value).toBeNull()
	})

	it("a stored task is unsaved only while it differs from what the form first showed", async () => {
		const { sc } = await started()
		const staged = opened(sc)
		expect([sc.hasUnsaved.value, sc.canSave.value]).toEqual([false, true])
		sc.values({ ...staged, title: "Other" }, true)
		expect(sc.hasUnsaved.value).toBe(true)
		sc.values({ ...staged, title: "Other" }, false)
		expect(sc.canSave.value).toBe(false)
		sc.values(staged, true)
		expect(sc.hasUnsaved.value).toBe(false)
		sc.closeTask()
		expect([sc.editTarget.value, sc.hasUnsaved.value, sc.canSave.value]).toEqual([null, false, false])
	})

	it("a conflict the server gave no revision for is not overwritten", async () => {
		const { sc } = await started()
		opened(sc)
		mocked.put.mockRejectedValueOnce(new ApiError(409, "Revision mismatch"))
		expect(await sc.saveTask(body, showNone)).toBe(false)
		expect(sc.conflict.value).toEqual({ message: "Revision mismatch", rev: undefined })
		expect(await sc.overwriteTask(showNone)).toBe(false)
		expect(mocked.put).toHaveBeenCalledTimes(1)
	})

	it("a save that fails otherwise keeps the edits", async () => {
		const { sc, notices } = await started()
		const staged = opened(sc)
		sc.values({ ...staged, title: "Other" }, true)
		mocked.put.mockRejectedValueOnce(new Error("offline"))
		expect(await sc.saveTask(body, showNone)).toBe(false)
		expect(sc.hasUnsaved.value).toBe(true)
		expect(notices).toEqual(["error: Failed to save the task: offline"])
	})

	it("a 422 shows a plugin field's problem on the field and lists the rest", async () => {
		const { sc } = await started()
		opened(sc)
		mocked.put.mockRejectedValue(new ApiError(422, "Invalid", { errors: [
			{ path: ["task", "content", "slideMinutes"], message: "Minimum 1" },
			{ path: ["trigger"], message: "Expected a trigger" },
		] }))
		const shown: unknown[] = []
		expect(await sc.saveTask(body, (errors: unknown[]) => { shown.push(...errors); return errors.length })).toBe(false)
		expect(shown).toEqual([{ path: ["slideMinutes"], message: "Minimum 1" }])
		expect(sc.serverProblems.value).toEqual(["trigger: Expected a trigger"])
		// a field the form could not show is listed instead of lost
		await sc.saveTask(body, showNone)
		expect(sc.serverProblems.value).toEqual(["trigger: Expected a trigger", "Invalid"])
	})

	it("Reload takes the server's version of the task; one that cannot be read says so", async () => {
		const { sc, notices } = await started()
		opened(sc)
		const base = mocked.get.getMockImplementation() as (path: string) => Promise<unknown>
		mocked.get.mockImplementation(async (path: string) => path === "/api/schedule/timer/{doc_id}/items/{item_id}" ? { task: { ...TASK, title: "Theirs", _rev: "r7" } } : base(path))
		expect(await sc.reloadTask()).toBe(true)
		expect(sc.editModel.value.title).toBe("Theirs")
		expect(sc.taskRev.value).toBe("r7")
		mocked.get.mockRejectedValueOnce(new Error("gone"))
		expect(await sc.reloadTask()).toBe(false)
		expect(notices).toEqual(["error: Failed to reload the task: gone"])
	})

	it("a delete names the revision; a stale one is a conflict", async () => {
		const { sc } = await started()
		opened(sc)
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

describe("a task changed elsewhere", () => {
	/** The page with the clock open in the dialog, following a fake link; `stored` is the task as the server has it. */
	async function following() {
		serve()
		const base = mocked.get.getMockImplementation() as (path: string, options?: unknown) => Promise<unknown>
		const stored = { task: { ...TASK } }
		mocked.get.mockImplementation(async (path: string, options?: unknown) =>
			path === "/api/schedule/timer/{doc_id}/items/{item_id}" ? { success: true, task: stored.task } : base(path, options))
		const fake = fakeLink()
		const sc = inApp(() => useSchedule(() => {}, { link: fake.link }))
		await sc.start()
		const staged = opened(sc)
		const elsewhere = async (title: string) => {
			stored.task = { ...TASK, _rev: "r7", title }
			fake.send(changedEvent("/api/schedule"))
			await settle()
			await settle()
		}
		return { sc, fake, staged, elsewhere }
	}

	it("with no edits the dialog shows the saved task, in a fresh form", async () => {
		const { sc, elsewhere } = await following()
		const form = sc.formKey.value
		await elsewhere("Theirs")
		expect([sc.editModel.value.title, sc.taskRev.value, sc.isStale.value, sc.formKey.value > form]).toEqual(["Theirs", "r7", false, true])
	})
	it("with edits it is stale: they stay until Reload, or Keep editing", async () => {
		const { sc, staged, elsewhere } = await following()
		sc.values({ ...staged, title: "Mine" }, true)
		await elsewhere("Theirs")
		expect([sc.isStale.value, sc.hasUnsaved.value, sc.editModel.value.title]).toEqual([true, true, "Clock"])
		sc.keepEditing()
		expect([sc.isStale.value, sc.hasUnsaved.value, sc.taskRev.value]).toEqual([false, true, "r1"])
		await sc.reloadTask()
		expect([sc.editModel.value.title, sc.taskRev.value]).toEqual(["Theirs", "r7"])
	})
	it("a new task, or a closed dialog, follows nothing", async () => {
		const { sc, fake } = await following()
		sc.closeTask()
		sc.newTask()
		const asked = mocked.get.mock.calls.length
		fake.send(changedEvent("/api/schedule"))
		await settle()
		expect(mocked.get.mock.calls.length).toBe(asked)
	})
})

describe("helpers", () => {
	it("a problem outside the plugin's content is listed with its path", () => {
		expect(splitTaskErrors([{ path: ["title"], message: "Required" }, {}])).toEqual({ onField: [], listed: ["title: Required", ""] })
	})
})
