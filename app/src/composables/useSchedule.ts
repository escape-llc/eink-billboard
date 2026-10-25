/**
 * The Scheduler's data (#510 A6): the window shown (a day, a week or the list, from an offset in days from today), the timer tasks and their runs
 * in it, the task being edited, and every call that loads or saves them. The page keeps its template, its dialogs, the form and the calendar's
 * look; what goes wrong is told through `notify` (the page shows it as a toast), so this runs and is tested without a component.
 *
 * The task dialog's cycle is the editor machine's (#550, `useEditor`): the form's values compared with the first it reported for the task, so an edit
 * put back is nothing to save; a stale save is a conflict whose Overwrite saves over the server's revision.
 */
import { computed, ref, shallowRef, toRaw } from "vue"
import { ApiError } from "../components/ApiClient"
import { api } from "../api/client"
import { rangeLabel, step, switchMode, taskRows, windowOf, type SchedulerMode, type TaskRow } from "../components/SchedulerView"
import type { EventInfo } from "../components/AlCalendar.vue"
import { browserZoneDifference, zonedParts } from "../components/CalendarTime"
import type { Descriptor } from "../components/FormDefs"
import type { PluginDef, TimerTasks } from "../components/ScheduleDefs"
import { useEditor } from "./useEditor"
import { useCatalog } from "../api/resources"

/** A list of what is installed, answered from the cache or asked once: its failure fails the load, as the timeline's own would. */
async function catalogRead(query: { refresh: () => Promise<{ error: Error | null }> }): Promise<void> {
	const state = await query.refresh()
	if (state.error) throw state.error
}

export type Notify = (severity: "success" | "warn" | "error", summary: string, detail: string) => void
/** What a delete came to: done, refused because the task changed (a conflict is shown), or failed (`notify` said why). */
export type DeleteOutcome = "done" | "conflict" | "failed"
/** A problem the server found in a task, by its path in the task (`["task", "content", "<field>"]`, `["trigger"]`). */
export type ServerError = { path?: unknown[], message?: string }
type FieldError = { path: unknown[], message: string }

// a timer task acts on the priority or overlay layer: the plugins for the playlist (background, foreground) are not offered.
// A stored task keeps its plugin (and shows it) even when it would not be offered now
const TIMER_LAYERS = ["layer-priority", "layer-overlay"]
export const DEFAULT_TRIGGER = {
	on_startup: false,
	day: { type: "dayofweek", days: [0, 1, 2, 3, 4, 5, 6] },
	time: { type: "specific", hour: 9, minute: 0 }
}

/** A 422's problems, sorted: a plugin field's goes on that field (`onField`, the path the form knows); the rest (title, trigger, plugin) is listed. */
export function splitTaskErrors(errors: ServerError[]) {
	const onField: FieldError[] = []
	const listed: string[] = []
	for(const err of errors) {
		const path = err.path ?? []
		if(path[0] === "task" && path[1] === "content" && typeof path[2] === "string") {
			onField.push({ path: [path[2]], message: err.message ?? "" })
		}
		else {
			listed.push(`${path.join(" / ")}${path.length ? ": " : ""}${err.message ?? ""}`)
		}
	}
	return { onField, listed }
}

/** A stored task as the editor holds it: its own fields, and the plugin's content beside them. */
export const stageTask = (evx: any) => ({
	id: evx.id,
	title: evx.title,
	enabled: evx.enabled,
	trigger: evx.trigger,
	plugin_name: evx.task.plugin_name,
	content: evx.task.content
})

export function useSchedule(notify: Notify) {
	// what is shown: a day, a week (from today's weekday), or each task once over that week; `offset` is days from today, never negative
	const mode = ref<SchedulerMode>("week")
	const offset = ref(0)
	// the window shown and today, in the zone the device's schedule runs in: both come from the server's answer (until it arrives, today here)
	const today = ref(zonedParts(new Date()).key)
	const firstDay = ref(zonedParts(new Date()).key)
	const dayCount = ref(7)
	const timeZone = ref<string | undefined>(undefined)
	// the stored tasks as the server sent them: not deeply reactive, so a row hands the editor plain data (structuredClone cannot copy a proxy)
	const schedules = shallowRef<Record<string, TimerTasks>>({})
	const eventList = ref<EventInfo[]>([])
	// what is installed, from the cache every view shares
	const catalog = useCatalog()
	const pluginList = computed<PluginDef[]>(() => catalog.plugins.data.value ?? [])
	const dataSources = computed<Descriptor[]>(() => catalog.dataSources.data.value ?? [])
	// the stored documents of timer tasks (a task is added to one of them)
	const documents = ref<{ id: string, name: string }[]>([])
	// the page shows a loading bar until the first load is done (a failure is a notice, never an empty page)
	const loading = ref(true)
	// the day the window was loaded on, in the device's zone: a page left open past midnight shows the new week
	let loadedDay = ""

	// what the dialog edits: a stored task (id) of a document; id null is a new task. Its revision is the editor's
	const editTarget = ref<{ schedule: string, id: string | null } | null>(null)
	const editModel = ref<Record<string, any>>({})
	// a new number for every task shown: the dialog's form starts afresh, so the first values it reports are that task's
	const formKey = ref(0)
	const newTaskDocument = ref<string | undefined>(undefined)
	// a delete is not the dialog's save: refused because the task changed, it says so, and Reload is the way on
	const refused = ref<string | null>(null)
	const conflictMessage = ref("")
	const serverProblems = ref<string[]>([])
	const busy = ref(false)
	let lastBody: Record<string, any> | undefined = undefined
	const editor = useEditor<Record<string, any>>({
		save: async (body, rev) => {
			const target = editTarget.value!
			if(target.id) await api.put("/api/schedule/timer/{doc_id}/items/{item_id}", taskPath(target.schedule, target.id), { ...body, _rev: rev })
			else await api.post("/api/schedule/timer/{doc_id}/items", { path: { doc_id: await ensureDocument() } }, body)
			// the dialog closes on a saved task: there is no revision to keep
			return undefined
		},
	})
	const taskRev = editor.rev
	const saving = computed(() => busy.value || editor.isBusy.value)
	const conflict = computed<{ message: string, rev: string | undefined } | null>(() =>
		editor.inConflict.value ? { message: conflictMessage.value, rev: editor.theirs.value } : refused.value !== null ? { message: refused.value, rev: undefined } : null)

	const zoneNote = computed(() => {
		const difference = browserZoneDifference(timeZone.value, new Date())
		return difference ? `Times are in the device's time zone (${timeZone.value}). Your browser is ${difference} of it.` : null
	})
	const rangeText = computed(() => rangeLabel(firstDay.value, dayCount.value))
	const rows = computed<TaskRow[]>(() => taskRows(eventList.value, schedules.value, id => pluginList.value.find(p => p.id === id)?.name ?? id))
	const selectedPlugin = computed(() => pluginList.value.find(p => p.id === editModel.value.plugin_name) || null)
	const timerPlugins = computed(() => pluginList.value.filter(p => (p.features ?? []).some(f => TIMER_LAYERS.includes(f))))
	const pluginOptions = computed(() => pluginList.value.filter(p => timerPlugins.value.includes(p) || p.id === editModel.value.plugin_name).map(p => ({ id: p.id, name: p.name })))

	// --- the window
	function loadTimeline(): Promise<void> {
		// today itself is the server's (its zone); a later day is asked for by its date
		const window = windowOf(mode.value, today.value, offset.value)
		return Promise.all([
			api.get("/api/schedule/tasks/render", { query: { days: window.days, start: offset.value > 0 ? window.start : undefined } }),
			catalogRead(catalog.plugins),
			catalogRead(catalog.dataSources),
			api.get("/api/schedule/timer/list"),
		]).then(([json, , , timed]) => {
			documents.value = timed.timed.map(d => ({ id: d.id, name: d.name }))
			if(!json.success) return
			// the response's first day is "today" in the device's zone (its ISO time is written in that zone)
			timeZone.value = typeof json.timezone === "string" ? json.timezone : undefined
			firstDay.value = String(json.start_ts).slice(0, 10)
			if(offset.value === 0) today.value = firstDay.value
			dayCount.value = json.days
			// a trigger is read as the form's (one a file holds that cannot be evaluated is in `invalid`, and has no runs)
			schedules.value = json.schedules as Record<string, TimerTasks>
			loadedDay = zonedParts(new Date(), timeZone.value).key
			eventList.value = json.render.map(rx => {
				const sref = schedules.value[rx.schedule]?.items.find(sx => sx.id === rx.id) ?? null
				const ei: EventInfo = { start: new Date(rx.scheduled_time), title: "my event", duration: 15, data: undefined }
				if(sref) {
					ei.title = `${sref.title} (${sref.task.plugin_name})`
					// the plugin's content: a number only when the plugin has one
					const minutes = sref.task.content.slideMinutes
					if(typeof minutes === "number" && minutes > 0) ei.duration = minutes
					// the document id travels with the task: that is what a change is addressed to
					ei.data = { ...sref, schedule: rx.schedule }
				}
				return ei
			})
		})
		.catch(ex => {
			console.error("render.unhandled", ex)
			notify("error", "Error", `Failed to load the schedule: ${ex.message || "Unknown error"}`)
		})
	}
	/** The page's first load. */
	function start() {
		return loadTimeline().finally(() => { loading.value = false })
	}
	function setMode(next: SchedulerMode) {
		if(next === mode.value) return
		mode.value = next
		offset.value = switchMode(next, offset.value)
		return loadTimeline()
	}
	function move(direction: 1 | -1) {
		offset.value = step(mode.value, offset.value, direction)
		return loadTimeline()
	}
	function goToday() {
		offset.value = 0
		return loadTimeline()
	}
	/** Called now and then by the page: on a new day in the device's zone, what was today is gone, and a week starts on the new today's weekday. */
	function checkDay(now = new Date()) {
		const day = zonedParts(now, timeZone.value).key
		if(!loadedDay || day === loadedDay) return
		offset.value = switchMode(mode.value, offset.value - 1)
		today.value = day
		return loadTimeline()
	}

	// --- the task in the dialog
	function resetMessages() {
		refused.value = null
		serverProblems.value = []
	}
	/** Open a stored task (a run's or a row's `data`): its staged copy for the editor, or null when its plugin is not installed (a notice says so). */
	function openTask(data: any): Record<string, any> | null {
		if(pluginList.value.length === 0 || !data) return null
		if(!pluginList.value.some(px => px.id === data.task.plugin_name)) {
			notify("warn", "Unknown plugin", "This task uses a plugin that is not installed.")
			return null
		}
		resetMessages()
		editTarget.value = { schedule: data.schedule, id: data.id }
		openedRev = data._rev
		// a run's data is reactive (the event list): structuredClone cannot copy a proxy
		return stageTask(structuredClone(toRaw(data)))
	}
	let openedRev: string | undefined = undefined
	/** Show a task in the dialog (`openTask`'s copy, or the server's after a reload): the machine hears of it first, then a fresh form shows it. */
	function showTask(staged: Record<string, any>, rev = openedRev) {
		editor.loaded(rev)
		editModel.value = staged
		formKey.value++
	}
	/** The dialog closed: nothing is being edited. */
	function closeTask() {
		editor.unload()
		editTarget.value = null
		editModel.value = {}
		resetMessages()
	}
	/** A new task with the first timer plugin, in the first document; false when no plugin can run on a timer. */
	function newTask(): boolean {
		const first = timerPlugins.value[0]
		if(!first) return false
		resetMessages()
		newTaskDocument.value = documents.value[0]?.id
		editTarget.value = { schedule: "", id: null }
		// a new task has nothing stored: saving it as it opened creates it
		showTask({ title: "", enabled: true, trigger: structuredClone(DEFAULT_TRIGGER), plugin_name: first.id, content: {} }, undefined)
		return true
	}
	const taskPath = (schedule: string, id: string) => ({ path: { doc_id: schedule, item_id: id } })
	/** The documents hold the tasks: a first task needs one to exist. */
	async function ensureDocument(): Promise<string> {
		if(newTaskDocument.value) return newTaskDocument.value
		const created = await api.post("/api/schedule/timer", {}, { name: "Timer tasks" })
		return created.id
	}
	/**
	 * Send the task over the revision it was loaded at (a stale one is a conflict the person can resolve). A plugin field's problem is
	 * handed to `showOnField`, which answers how many it could show; the rest is listed in `serverProblems`. True when it was saved.
	 */
	async function saveTask(body: Record<string, any>, showOnField: (errors: FieldError[]) => number): Promise<boolean> {
		if(!editTarget.value) return false
		resetMessages()
		lastBody = body
		const { outcome, error } = await editor.save(body)
		const ex = error as any
		if(outcome === "saved") {
			notify("success", "Success", "Task saved")
			return true
		}
		if(outcome === "conflict") conflictMessage.value = ex.message
		else if(outcome === "failed" && ex instanceof ApiError && ex.status === 422 && Array.isArray(ex.body?.errors)) {
			const { onField, listed } = splitTaskErrors(ex.body.errors)
			const shown = onField.length > 0 ? showOnField(onField) : 0
			serverProblems.value = shown < onField.length || listed.length > 0 ? [...listed, ...(shown < onField.length ? [ex.message] : [])] : []
		}
		else if(outcome === "failed") notify("error", "Error", `Failed to save the task: ${ex?.message || "Unknown error"}`)
		return false
	}
	/** Keep my version: send it again over the revision the server has now. */
	async function overwriteTask(showOnField: (errors: FieldError[]) => number): Promise<boolean> {
		if(!lastBody || !editor.keep()) return false
		return saveTask(lastBody, showOnField)
	}
	/** Someone else changed the task: take their version (the edits are dropped). False when it could not be read (a notice says so). */
	async function reloadTask(): Promise<boolean> {
		const target = editTarget.value
		if(!target?.id) return true
		try {
			const rx = await api.get("/api/schedule/timer/{doc_id}/items/{item_id}", taskPath(target.schedule, target.id))
			resetMessages()
			showTask(stageTask(rx.task), rx.task._rev)
			return true
		}
		catch(ex: any) {
			notify("error", "Error", `Failed to reload the task: ${ex.message || "Unknown error"}`)
			return false
		}
	}
	async function deleteTask(): Promise<DeleteOutcome> {
		const target = editTarget.value
		const rev = taskRev.value
		if(!target?.id || !rev) return "failed"
		busy.value = true
		try {
			await api.delete("/api/schedule/timer/{doc_id}/items/{item_id}", { path: { doc_id: target.schedule, item_id: target.id }, query: { rev } })
			notify("success", "Success", "Task deleted")
			return "done"
		}
		catch(ex: any) {
			if(ex instanceof ApiError && ex.status === 409) {
				refused.value = "The task changed since it was loaded; reload it before deleting."
				return "conflict"
			}
			notify("error", "Error", `Failed to delete the task: ${ex.message || "Unknown error"}`)
			return "failed"
		}
		finally {
			busy.value = false
		}
	}

	return {
		mode, offset, today, firstDay, dayCount, timeZone, schedules, eventList, pluginList, dataSources, documents, loading,
		editTarget, editModel, formKey, newTaskDocument, conflict, serverProblems, saving, taskRev,
		hasUnsaved: editor.hasUnsaved, canSave: editor.canSave, values: editor.values, stop: editor.stop,
		zoneNote, rangeText, rows, selectedPlugin, timerPlugins, pluginOptions,
		loadTimeline, start, setMode, move, goToday, checkDay,
		openTask, showTask, closeTask, newTask, saveTask, overwriteTask, reloadTask, deleteTask,
	}
}
