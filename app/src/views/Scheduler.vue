<template>
	<div class="flex flex-column" style="height:80vh;width:100%;justify-items: stretch;align-items: stretch;">
	<Toolbar class="p-0">
		<template #start>
			<div style="font-size:150%">Scheduler</div>
		</template>
		<template #end>
			<Button size="small" label="New task" icon="pi pi-plus" :disabled="timerPlugins.length === 0" @click="handleNew" />
		</template>
	</Toolbar>
	<Message v-if="zoneNote" severity="info" :closable="false" size="small" class="my-1" data-testid="zone-note">{{ zoneNote }}</Message>
	<AlCalendar style="width:100%" class="calendar" :firstDay="firstDay" :dayCount="dayCount" :timeZone="timeZone" :timeRange="timeRange" :eventList="eventList">
		<template #dayheader="{ day }">
			<div class="day-header" :style="{'grid-column': day.column, 'grid-row': day.row }"
				:class="{'day-header-weekend': day.weekday === 0 || day.weekday === 6, 'day-header-today': day.today }">
				<div>
					<span class="day-header-day">{{ day.dayOfMonth }}</span>
					<span class="day-header-dow">{{ WEEKDAYS[day.weekday] }}</span>
				</div>
			</div>
		</template>
		<template #timeheader="{ time }">
			<div class="time-header" :style="{'grid-row':time.row,'grid-column':time.column}">
				<div>
					<span v-if="time.minute === 0" class="time-header-hour">{{ String(time.hour).padStart(2, '0') }}</span>
					<span class="time-header-minute">{{ String(time.minute).padStart(2, '0') }}</span>
				</div>
			</div>
		</template>
		<template #event="{ day, event }">
			<div class="event" role="button" tabindex="0" :aria-label="`Edit ${event.event.title}`"
				:style="{'grid-row': `${event.row} / span ${event.span}`, 'background-color': derefColor(event), 'border-left': `5px solid color-mix(in srgb, ${sidebarColor(event)} 80%, #333 20%)`}"
				@click="handleEventClick($event, day, event)"
				@keydown.enter.prevent="handleEventClick($event, day, event)"
				@keydown.space.prevent="handleEventClick($event, day, event)">
				<div class="event-title">{{ event.continued ? "↳ " : "" }}{{ event.event.title }}</div>
			</div>
		</template>
	</AlCalendar>
	<Dialog v-model:visible="dialogOpen" modal :header="editTarget?.id ? 'Edit task' : 'New task'" style="width:60%; font-size:90%">
		<Message v-if="conflict" severity="warn" :closable="false" class="mb-2">
			<div class="flex align-items-center gap-2">
				<span>{{ conflict.message }}</span>
				<Button size="small" label="Reload" icon="pi pi-refresh" severity="secondary" @click="reloadTask" />
				<Button v-if="conflict.rev" size="small" label="Overwrite" icon="pi pi-upload" severity="danger" @click="overwriteTask" />
			</div>
		</Message>
		<Message v-for="(problem, index) in serverProblems" :key="index" severity="error" size="small" variant="simple">{{ problem }}</Message>
		<BasicForm v-if="selectedPlugin" ref="bf" :form="selectedPlugin.instanceSettings" :initialValues="editModel.content" :baseUrl="API_URL"
			:beforeFieldsSchema="beforeFieldsSchema" :addInitialValues="addInitialValues"
			@validate="onValidated" @submit="submitForm"
			class="form">
			<template #header>
				<Toolbar style="width:100%" class="p-1 mt-2">
					<template #start>
						<div style="font-weight: bold;font-size:150%">Item Settings</div>
					</template>
					<template #end>
						<InputGroup>
							<Button size="small" icon="pi pi-check" severity="success" aria-label="Save" :disabled="!editModelValid || saving" @click="handleSubmit" />
							<Button size="small" icon="pi pi-times" severity="danger" aria-label="Reset" @click="handleReset" />
						</InputGroup>
					</template>
				</Toolbar>
			</template>
			<template #group-header="slotProps">
				<h3 class="mb-0">{{ slotProps.label }}</h3>
			</template>
			<template #before-fields>
				<InputGroup v-if="!editTarget?.id && documents.length > 1">
					<InputGroupAddon>
						<label :style="{'width': fieldNameWidth, 'max-width': fieldNameWidth }" style="flex-shrink:0;flex-grow:1">Schedule</label>
					</InputGroupAddon>
					<Select :options="documents" optionLabel="name" optionValue="id" v-model="newTaskDocument" />
				</InputGroup>
				<InputGroup>
					<InputGroupAddon>
						<label :style="{'width': fieldNameWidth, 'max-width': fieldNameWidth }" fluid style="flex-shrink:0;flex-grow:1">Title</label>
					</InputGroupAddon>
					<InputText style="flex-grow:1" size="small" name="title" fluid v-model="editModel.title" />
				</InputGroup>
				<Message v-if="!isTitleValid"
					severity="error" size="small" variant="simple">{{ titleErrorMessage }}</Message>
				<InputGroup>
					<InputGroupAddon>
						<label :style="{'width': fieldNameWidth, 'max-width': fieldNameWidth }" fluid style="flex-shrink:0;flex-grow:1">Enabled</label>
					</InputGroupAddon>
					<InputGroupAddon style="flex-grow:1;justify-content:flex-start">
						<Checkbox v-model="editModel.enabled" fluid binary name="enabled" />
					</InputGroupAddon>
				</InputGroup>
				<InputGroup>
					<InputGroupAddon>
						<label :style="{'width': fieldNameWidth, 'max-width': fieldNameWidth }" fluid style="flex-shrink:0;flex-grow:1">Trigger</label>
					</InputGroupAddon>
					<InputGroupAddon style="flex-grow:1;justify-content:flex-start">
						<FormField name="trigger" v-slot="$field" :validateOnValueUpdate="true" :initialValue="editModel.trigger" style="display:flex;flex-grow:1">
							<TimedTrigger :modelValue="$field.value" parentPropName="trigger." :fieldNameWidth="fieldNameWidth" @change="$field.props.onChange" />
						</FormField>
					</InputGroupAddon>
				</InputGroup>
				<InputGroup>
					<InputGroupAddon>
						<label :style="{'width': fieldNameWidth, 'max-width': fieldNameWidth }" style="flex-shrink:0;flex-grow:1">Plugin</label>
					</InputGroupAddon>
					<Select :options="pluginOptions" optionLabel="name" optionValue="id" name="plugin_name" v-model="editModel.plugin_name" />
				</InputGroup>
				<Message v-if="!isPluginValid"
					severity="error" size="small" variant="simple">{{ pluginErrorMessage }}</Message>
			</template>
		</BasicForm>
		<div class="flex gap-2 pt-2 justify-content-between">
			<Button v-if="editTarget?.id" type="button" label="Delete" icon="pi pi-trash" severity="danger" variant="text" @click="deleteOpen = true"></Button>
			<span v-else></span>
			<div class="flex gap-2">
				<Button type="button" label="Cancel" severity="secondary" @click="dialogOpen = false"></Button>
				<Button type="button" label="Save" :disabled="!editModelValid || saving" @click="handleSubmit"></Button>
			</div>
		</div>
	</Dialog>
	<Dialog v-model:visible="deleteOpen" modal header="Delete task?" style="width:24rem">
		<p class="mt-0">"{{ editModel.title }}" will be removed from the schedule.</p>
		<div class="flex gap-2 justify-content-end">
			<Button type="button" label="Keep" severity="secondary" @click="deleteOpen = false"></Button>
			<Button type="button" label="Delete" severity="danger" :disabled="saving" @click="deleteTask"></Button>
		</div>
	</Dialog>
	</div>
</template>
<script setup lang="ts">
import { ApiError, apiDelete, apiJson, apiPost, apiPut } from "../components/ApiClient"
import { InputGroup, InputGroupAddon, Button, Dialog, Toolbar, Select, Checkbox, InputText, Message, useToast } from "primevue"
import FormField from '@primevue/forms/formfield';
import AlCalendar from "../components/AlCalendar.vue"
import type { TimeRange, EventInfo } from "../components/AlCalendar.vue"
import { browserZoneDifference, zonedParts } from "../components/CalendarTime"
import { ref, onMounted, onBeforeUnmount, nextTick, toRaw, provide, computed } from "vue"
import BasicForm, { type ValidateEventData } from "../components/BasicForm.vue"
import type { FormDef } from "../components/FormDefs"
import type { PluginDef } from "../components/ScheduleDefs"
import { TriggerDefSchema } from "../components/ScheduleDefs"
import TimedTrigger from "../components/TimedTrigger.vue"
import z from "zod";

const bf = ref<InstanceType<typeof BasicForm>>()
const fieldNameWidth = "10rem";
const form = ref<FormDef>()
// the week shown, in the zone the device's schedule runs in: both come from the server's answer (until it arrives, today here)
const zoneNote = computed(() => {
	const difference = browserZoneDifference(timeZone.value, new Date())
	return difference ? `Times are in the device's time zone (${timeZone.value}). Your browser is ${difference} of it.` : null
})
const firstDay = ref(zonedParts(new Date()).key)
const dayCount = ref(7)
const timeZone = ref<string|undefined>(undefined)
const WEEKDAYS = (() => {
	const format = new Intl.DateTimeFormat("en-US", { weekday: "short", timeZone: "UTC" })
	return Array.from({ length: 7 }, (_, weekday) => format.format(new Date(Date.UTC(2023, 0, 1 + weekday))))
})()
const timeRange = ref<TimeRange>({start: 0, end: 1440, interval:30 })
const eventList = ref<EventInfo[]>([])
const dialogOpen = ref(false)
const currentEvent = ref()
const toast = useToast()
const TIMER_URL = `${import.meta.env.VITE_API_URL}api/schedule/timer`
// the stored documents of timer tasks (a task is added to one of them)
const documents = ref<{ id: string, name: string }[]>([])
const newTaskDocument = ref<string|undefined>(undefined)
// what the dialog edits: a stored task (id) of a document, with the revision it was loaded at; id null is a new task
const editTarget = ref<{ schedule: string, id: string|null, rev: string|undefined }|null>(null)
const conflict = ref<{ message: string, rev: string|undefined }|null>(null)
const serverProblems = ref<string[]>([])
const saving = ref(false)
const deleteOpen = ref(false)
let lastBody: Record<string, any>|undefined = undefined

type DropdownOption = {
	id: string,
	name: string
}
// editing model separate from the track until Apply
const editModel = ref<Record<string,any>>({} as any) // start with empty model, populate on track select
const editModelValid = ref(false)
const isTitleValid = ref(false)
const titleErrorMessage = ref<string|undefined>(undefined)
const isPluginValid = ref(false)
const pluginErrorMessage = ref<string|undefined>(undefined)
const selectedPlugin = computed(() => pluginList.value.find(p => p.id === editModel.value.plugin_name) || null)
// a timer task acts on the priority or overlay layer: the plugins for the playlist (background, foreground) are not offered.
// A stored task keeps its plugin (and shows it) even when it would not be offered now
const TIMER_LAYERS = ["layer-priority", "layer-overlay"]
const timerPlugins = computed(() => pluginList.value.filter(p => (p.features ?? []).some(f => TIMER_LAYERS.includes(f))))
const pluginOptions = computed<DropdownOption[]>(() => pluginList.value.filter(p => timerPlugins.value.includes(p) || p.id === editModel.value.plugin_name).map(p => ({ id: p.id, name: p.name })))

function derefSchedule(schedules:Record<string,any>, sid:string, id:string) {
	if(sid in schedules) {
		const schedule = schedules[sid]
		const item = schedule.items.find((sx: any) => sx.id === id)
		return item
	}
	return null
}
const color_map: Map<string, string> = new Map()

function derefColor(event:any):string {
	const id = event.event.data.id
	if(color_map.has(id)) {
		return color_map.get(id) as string
	}
	else {
		const hue = 180 + color_map.size * 137.508/4; // use golden angle increment for even distribution
		const newColor = `hsl(${hue % 360}, 100%, 90%)`
		color_map.set(id, newColor)
		return newColor
	}
}
function sidebarColor(event:any):string {
	const enabled = event.event.data.enabled
	if(enabled) {
		return "rgb(0,255,0)"
	}
	else {
		return "rgb(180,180,180)"
	}
}
const API_URL = import.meta.env.VITE_API_URL

const pluginList = ref<PluginDef[]>([])
const dataSources = ref([])
provide("settingsPluginsList", pluginList)
provide("settingsDataSourcesList", dataSources)


function loadTimeline(): Promise<void> {
	const renderUrl = `${API_URL}api/schedule/tasks/render`
	const listPluginsUrl = `${API_URL}api/plugins/list`
	const listDatasourcesUrl = `${API_URL}api/datasources/list`
	const pxs = [
		apiJson(renderUrl),
		apiJson(listPluginsUrl),
		apiJson(listDatasourcesUrl),
		apiJson(`${TIMER_URL}/list`),
	]
	return Promise.all(pxs).then(rxs => {
		const json = rxs[0]
		pluginList.value = rxs[1]
		dataSources.value = rxs[2]
		documents.value = (rxs[3].timed ?? []).map((d: any) => ({ id: d.id, name: d.name }))
		if(json.success) {
			// the response's first day is "today" in the device's zone (its ISO time is written in that zone)
			timeZone.value = typeof json.timezone === "string" ? json.timezone : undefined
			firstDay.value = String(json.start_ts).slice(0, 10)
			dayCount.value = json.days
			loadedDay = zonedParts(new Date(), timeZone.value).key
			const events:EventInfo[] = []
			json.render.forEach((rx: any) => {
				rx.start = new Date(rx.scheduled_time)
				const sref = derefSchedule(json.schedules, rx.schedule, rx.id)
				const ei = {
					start: rx.start,
					title: "my event",
					duration: 15,
					data: undefined
				} satisfies EventInfo
				if(sref) {
					ei.title = `${sref.title} (${sref.task.plugin_name})`
					if(sref.task.content.slideMinutes) {
						ei.duration = sref.task.content.slideMinutes
					}
					// the document id travels with the task: that is what a change is addressed to
					ei.data = { ...sref, schedule: rx.schedule }
				}
				events.push(ei)
			})
			eventList.value = events
		}
	})
	.catch(ex => {
		console.error("render.unhandled", ex)
		toast.add({severity:'error', summary: 'Error', detail: `Failed to load the schedule: ${ex.message || 'Unknown error'}`, life: 5000});
	})
}
// a page left open past midnight (in the device's zone) shows the new week
let loadedDay = ""
let dayWatch: ReturnType<typeof setInterval>|undefined = undefined
onMounted(() => {
	loadTimeline()
	dayWatch = setInterval(() => {
		if(loadedDay && zonedParts(new Date(), timeZone.value).key !== loadedDay) loadTimeline()
	}, 60_000)
})
onBeforeUnmount(() => clearInterval(dayWatch))
const beforeFieldsSchema = (resv: Record<string, z.ZodTypeAny>) => {
	resv['title'] = z.string().min(1, "Title is required")
	resv['enabled'] = z.boolean()
	resv['plugin_name'] = z.string().min(1, "Plugin is required")
	resv['trigger'] = TriggerDefSchema
}
const addInitialValues = () => {
	const ox = {
		title: editModel.value.title || "",
		enabled: editModel.value.enabled || false,
		plugin_name: editModel.value.plugin_name || "",
		trigger: editModel.value.trigger || {},
	}
	return ox
}
const onValidated = ({ result }: ValidateEventData) => {
	if(result.success) {
		editModelValid.value = true
		isTitleValid.value = true
		titleErrorMessage.value = undefined
		return;
	}
	else {
		editModelValid.value = false
		let issue = result.error.issues.find((ix) => ix.path[0] === 'title');
		if(issue) {
			isTitleValid.value = false
			titleErrorMessage.value = issue.message
		}
		else {
			isTitleValid.value = true
			titleErrorMessage.value = undefined
		}
		issue = result.error.issues.find((ix) => ix.path[0] === 'plugin_name');
		if(issue) {
			isPluginValid.value = false
			pluginErrorMessage.value = issue.message
		}
		else {
			isPluginValid.value = true
			pluginErrorMessage.value = undefined
		}
	}
}
function resetMessages() {
	conflict.value = null
	serverProblems.value = []
}
const stageTask = (evx: any) => ({
	id: evx.id,
	title: evx.title,
	enabled: evx.enabled,
	trigger: evx.trigger,
	plugin_name: evx.task.plugin_name,
	content: evx.task.content
})
const handleEventClick = (_event: any, _day: any, event: any) => {
	const data = event.event.data
	if(pluginList.value.length > 0 && data) {
		const target = pluginList.value.find(px => px.id === data.task.plugin_name)
		if(target) {
			resetMessages()
			currentEvent.value = event
			editTarget.value = { schedule: data.schedule, id: data.id, rev: data._rev }
			dialogOpen.value = true
			form.value = structuredClone(toRaw(target.instanceSettings))
			nextTick().then(_ => {
				editModel.value = stageTask(structuredClone(toRaw(data)))
			})
		}
		else {
			toast.add({severity:'warn', summary: 'Unknown plugin', detail: `This task uses a plugin that is not installed.`, life: 5000});
		}
	}
}
const DEFAULT_TRIGGER = {
	on_startup: false,
	day: { type: "dayofweek", days: [0, 1, 2, 3, 4, 5, 6] },
	time: { type: "specific", hour: 9, minute: 0 }
}
const handleNew = () => {
	const first = timerPlugins.value[0]
	if(!first) return
	resetMessages()
	currentEvent.value = undefined
	newTaskDocument.value = documents.value[0]?.id
	editTarget.value = { schedule: "", id: null, rev: undefined }
	editModel.value = { title: "", enabled: true, trigger: structuredClone(DEFAULT_TRIGGER), plugin_name: first.id, content: {} }
	dialogOpen.value = true
}
const taskUrl = (schedule: string, id: string) => `${TIMER_URL}/${encodeURIComponent(schedule)}/items/${encodeURIComponent(id)}`
/** The documents hold the tasks: a first task needs one to exist. */
async function ensureDocument(): Promise<string> {
	if(newTaskDocument.value) return newTaskDocument.value
	const created = await apiPost(TIMER_URL, { name: "Timer tasks" })
	return created.id
}
/** Send the task; `rev` is the revision it was loaded at (a stale one is a 409, which the dialog lets the person resolve). */
async function saveTask(body: Record<string, any>, rev: string|undefined) {
	const target = editTarget.value
	if(!target) return
	saving.value = true
	resetMessages()
	lastBody = body
	try {
		if(target.id) {
			await apiPut(taskUrl(target.schedule, target.id), { ...body, _rev: rev })
		}
		else {
			await apiPost(`${TIMER_URL}/${encodeURIComponent(await ensureDocument())}/items`, body)
		}
		toast.add({severity:'success', summary: 'Success', detail: 'Task saved', life: 3000});
		dialogOpen.value = false
		await loadTimeline()
	}
	catch(ex: any) {
		if(ex instanceof ApiError && ex.status === 409) {
			conflict.value = { message: ex.message, rev: typeof ex.body?.rev === "string" ? ex.body.rev : undefined }
		}
		else if(ex instanceof ApiError && ex.status === 422 && Array.isArray(ex.body?.errors)) {
			// a plugin field's problem shows on that field; the rest (title, trigger, plugin) is listed above the form
			const fieldErrors: { path: unknown[], message: string }[] = []
			const others: string[] = []
			for(const err of ex.body.errors as { path?: unknown[], message?: string }[]) {
				const path = err.path ?? []
				if(path[0] === "task" && path[1] === "content" && typeof path[2] === "string") {
					fieldErrors.push({ path: [path[2]], message: err.message ?? "" })
				}
				else {
					others.push(`${path.join(" / ")}${path.length ? ": " : ""}${err.message ?? ""}`)
				}
			}
			const shown = fieldErrors.length > 0 ? (bf.value?.setServerErrors(fieldErrors) ?? 0) : 0
			serverProblems.value = shown < fieldErrors.length || others.length > 0 ? [...others, ...(shown < fieldErrors.length ? [ex.message] : [])] : []
		}
		else {
			toast.add({severity:'error', summary: 'Error', detail: `Failed to save the task: ${ex.message || 'Unknown error'}`, life: 5000});
		}
	}
	finally {
		saving.value = false
	}
}
const submitForm = ({ result }: { result?: { success: boolean, data?: Record<string, any> } }) => {
	if(!result?.success || !result.data || !editTarget.value) return
	// the fields the page adds around the plugin's own (see beforeFieldsSchema) are the task's; the rest is its content
	const { title, enabled, plugin_name, trigger, ...content } = result.data
	saveTask({ title, enabled, trigger, task: { plugin_name, content } }, editTarget.value.rev)
}
/** Someone else changed the task: take their version (the edits are dropped). */
async function reloadTask() {
	const target = editTarget.value
	if(!target?.id) return
	try {
		const rx = await apiJson(taskUrl(target.schedule, target.id))
		editTarget.value = { ...target, rev: rx.task._rev }
		resetMessages()
		editModel.value = stageTask(rx.task)
	}
	catch(ex: any) {
		toast.add({severity:'error', summary: 'Error', detail: `Failed to reload the task: ${ex.message || 'Unknown error'}`, life: 5000});
		dialogOpen.value = false
		await loadTimeline()
	}
}
/** Keep my version: send it again at the revision the server has now. */
function overwriteTask() {
	if(!lastBody || !conflict.value?.rev) return
	saveTask(lastBody, conflict.value.rev)
}
async function deleteTask() {
	const target = editTarget.value
	if(!target?.id || !target.rev) return
	saving.value = true
	try {
		await apiDelete(`${taskUrl(target.schedule, target.id)}?rev=${encodeURIComponent(target.rev)}`)
		toast.add({severity:'success', summary: 'Success', detail: 'Task deleted', life: 3000});
		deleteOpen.value = false
		dialogOpen.value = false
		await loadTimeline()
	}
	catch(ex: any) {
		deleteOpen.value = false
		if(ex instanceof ApiError && ex.status === 409) {
			conflict.value = { message: "The task changed since it was loaded; reload it before deleting.", rev: undefined }
		}
		else {
			toast.add({severity:'error', summary: 'Error', detail: `Failed to delete the task: ${ex.message || 'Unknown error'}`, life: 5000});
		}
	}
	finally {
		saving.value = false
	}
}
const handleReset = () => {
//	cancelEdit()
	bf.value?.reset()
}
const handleSubmit = () => {
	bf.value?.submit()
}
</script>
<style scoped>
.calendar {
	height: calc(var(--calendar-height));
}
.day-header {
	display: flex;
	align-items: center;
	justify-content: center;
	font-weight: bold;
	background-color: #e9e9e9;
	border-bottom: 1px solid #ccc;
	height: fit-content;
}
.day-header-day {
	font-size: 2rem;
	vertical-align: baseline;
}
.day-header-dow {
	font-size: 1.2rem;
	margin-left:.15rem;
	vertical-align: baseline;
}
.day-header-weekend {
	color: red;
}
.day-header-today {
	border-top: 2px solid blue;
}
.time-header {
	display: flex;
	align-items: center;
	justify-content: flex-end;
	padding-right: .1rem;
	font-size: 0.8rem;
	color: #555;
	border-top: 1px dashed #eee;
	height:fit-content;
}
.time-header:first-child {
	border-bottom: none; /* No dashed line above the first label */
}
.time-header-hour {
	font-size: 1rem;
	font-weight: bold;
	vertical-align: baseline;
}
.time-header-minute {
	font-size: .75rem;
	margin-left:.1rem;
	vertical-align: text-top;
}
.event {
	cursor: pointer;
	margin: .1rem .2rem;
	padding: .2rem .4rem;
	border-radius: 4px;
	font-size: 0.9em;
	color: black;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
	box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}
.event-title {
	text-overflow: ellipsis;
	white-space: nowrap;
	overflow: hidden;
	vertical-align: middle;
	margin:0;
	padding:0;
}
</style>
<style>
:root {
	--calendar-height: 800px;
}
</style>