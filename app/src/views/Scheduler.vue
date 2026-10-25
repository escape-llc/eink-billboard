<template>
	<div class="flex flex-column scheduler" style="width:100%;justify-items: stretch;align-items: stretch;">
	<Toolbar class="p-2">
		<template #start>
			<div style="font-size:150%">Scheduler</div>
		</template>
		<template #center>
			<span class="range-label" data-testid="range">{{ rangeText }}</span>
		</template>
		<template #end>
			<!-- one group: the view (a day or a week from today's weekday, or each task once), back / today / forward (never before today), a new task -->
			<InputGroup class="scheduler-actions">
				<Button v-for="m in MODES" :key="m.value" class="short-on-phone" size="small" :icon="m.icon" :label="m.label" :aria-label="m.label" :aria-pressed="mode === m.value"
					:severity="mode === m.value ? 'contrast' : 'secondary'" @click="setMode(m.value)" />
				<Button size="small" icon="mi mi-chevron-left" severity="secondary" aria-label="Back" :title="mode === 'day' ? 'The day before' : 'The week before'" :disabled="offset === 0" @click="move(-1)" />
				<Button size="small" label="Today" severity="secondary" :disabled="offset === 0" @click="goToday" />
				<Button size="small" icon="mi mi-chevron-right" severity="secondary" aria-label="Forward" :title="mode === 'day' ? 'The next day' : 'The next week'" @click="move(1)" />
				<Button class="short-on-phone" size="small" label="New task" aria-label="New task" icon="mi mi-add" :disabled="timerPlugins.length === 0" @click="handleNew" />
			</InputGroup>
		</template>
	</Toolbar>
	<ProgressBar v-if="loading" mode="indeterminate" style="height:4px" aria-label="Loading" data-testid="loading" />
	<Message v-if="zoneNote" severity="info" :closable="false" size="small" class="my-1" data-testid="zone-note">{{ zoneNote }}</Message>
	<div v-if="mode === 'list'" class="task-list" data-testid="task-list">
		<DataTable size="small" :value="rows" dataKey="key" rowHover scrollable scrollHeight="flex" class="task-table">
			<Column header="Task">
				<template #body="{ data }">
					<Button size="small" variant="link" class="task-title" :label="data.title" :aria-label="`Edit ${data.title}`" @click="openRow(data)" />
				</template>
			</Column>
			<Column field="plugin" header="Plugin" />
			<Column field="trigger" header="Trigger" />
			<Column header="Next run">
				<template #body="{ data }">{{ data.next ? runText(data.next) : (data.enabled ? "Not this week" : "") }}</template>
			</Column>
			<Column header="Run At Startup" bodyClass="startup">
				<template #body="{ data }">
					<i v-if="data.startup" class="mi mi-check" role="img" aria-label="Runs at startup"></i>
					<span v-else class="p-hidden-accessible">No</span>
				</template>
			</Column>
			<Column header="Runs" bodyClass="runs">
				<template #body="{ data }">{{ data.runs }}</template>
			</Column>
			<Column header="">
				<template #body="{ data }"><Tag v-if="!data.enabled" severity="secondary" value="off" /></template>
			</Column>
			<template #empty>No timer tasks.</template>
		</DataTable>
	</div>
	<AlCalendar v-else style="width:100%" class="calendar" :firstDay="firstDay" :dayCount="dayCount" :timeZone="timeZone" :timeRange="timeRange" :eventList="eventList">
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
	<Dialog :visible="dialogOpen" @update:visible="onDialogVisible" modal :header="editTarget?.id ? 'Edit task' : 'New task'" style="width:60%; min-width:min(36rem, 95vw); font-size:90%">
		<Message size="small" v-if="conflict" severity="warn" :closable="false" class="mb-2">
			<div class="flex align-items-center gap-2">
				<span>{{ conflict.message }}</span>
				<Button size="small" label="Reload" icon="mi mi-refresh" severity="secondary" @click="reloadTask" />
				<Button v-if="conflict.rev" size="small" label="Overwrite" icon="mi mi-upload" severity="danger" @click="overwriteTask" />
			</div>
		</Message>
		<Message size="small" v-if="isStale" severity="info" :closable="false" class="mb-2 changed-elsewhere">
			<div class="flex align-items-center gap-2 flex-wrap">
				<span>Changed elsewhere: this task was saved somewhere else while you were editing it.</span>
				<Button size="small" label="Reload" icon="mi mi-refresh" severity="secondary" title="Drop your changes and show the saved task" @click="reloadTask" />
				<Button size="small" label="Keep editing" icon="mi mi-edit" severity="secondary" title="Keep your changes; saving them asks whether to overwrite" @click="keepEditing" />
			</div>
		</Message>
		<Message v-for="(problem, index) in serverProblems" :key="index" severity="error" size="small" variant="simple">{{ problem }}</Message>
		<BasicForm v-if="selectedPlugin" :key="formKey" ref="bf" :form="selectedPlugin.instanceSettings" :owner="{ kind: 'plugin', id: selectedPlugin.id }" :initialValues="editModel.content" :baseUrl="API_URL" :showHelp="showHelp" :showChanges="!!editTarget?.id"
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
							<HelpToggle v-model="showHelp" />
							<!-- a stored task can be deleted from here; the dialog's own close button leaves without saving -->
							<Button v-if="editTarget?.id" size="small" icon="mi mi-delete" severity="danger" variant="outlined" aria-label="Delete" title="Delete this task" @click="deleteOpen = true" />
							<Button size="small" icon="mi mi-check" severity="success" aria-label="Save" :title="saveTitle" :disabled="!canSave || unchanged" @click="handleSubmit" />
							<Button size="small" icon="mi mi-close" severity="danger" aria-label="Cancel" title="Close without saving" @click="handleCancel" />
						</InputGroup>
					</template>
				</Toolbar>
			</template>
			<template #group-header="slotProps">
				<h3 class="mb-0">{{ slotProps.title }}</h3>
			</template>
			<template #before-fields>
				<InputGroup class="field-row" v-if="!editTarget?.id && documents.length > 1">
					<InputGroupAddon class="field-label">
						<label class="field-title" :style="{ '--label-width': fieldNameWidth }">Schedule</label>
					</InputGroupAddon>
					<Select size="small" :options="documents" optionLabel="name" optionValue="id" v-model="newTaskDocument" />
				</InputGroup>
				<InputGroup class="field-row">
					<InputGroupAddon class="field-label">
						<label class="field-title" :style="{ '--label-width': fieldNameWidth }">Title</label>
					</InputGroupAddon>
					<InputText style="flex-grow:1" size="small" name="title" fluid v-model="editModel.title" />
				</InputGroup>
				<Message v-if="!isTitleValid"
					severity="error" size="small" variant="simple">{{ titleErrorMessage }}</Message>
				<InputGroup class="field-row">
					<InputGroupAddon class="field-label">
						<label class="field-title" :style="{ '--label-width': fieldNameWidth }">Enabled</label>
					</InputGroupAddon>
					<InputGroupAddon style="flex-grow:1;justify-content:flex-start">
						<Checkbox v-model="editModel.enabled" fluid binary name="enabled" />
					</InputGroupAddon>
				</InputGroup>
				<div class="trigger-heading">Trigger</div>
				<FormField name="trigger" v-slot="$field" :validateOnValueUpdate="true" :initialValue="editModel.trigger" style="display:flex;flex-grow:1">
							<TimedTrigger :modelValue="$field.value" parentPropName="trigger." :fieldNameWidth="fieldNameWidth" @change="$field.props.onChange" />
						</FormField>
				<InputGroup class="field-row">
					<InputGroupAddon class="field-label">
						<label class="field-title" :style="{ '--label-width': fieldNameWidth }">Plugin</label>
					</InputGroupAddon>
					<Select size="small" :options="pluginOptions" optionLabel="name" optionValue="id" name="plugin_name" v-model="editModel.plugin_name" />
				</InputGroup>
				<Message v-if="!isPluginValid"
					severity="error" size="small" variant="simple">{{ pluginErrorMessage }}</Message>
			</template>
		</BasicForm>
	</Dialog>
	<Dialog v-model:visible="deleteOpen" modal header="Delete task?" style="width:24rem;max-width:95vw">
		<p class="mt-0">"{{ editModel.title }}" will be removed from the schedule.</p>
		<div class="flex gap-2 justify-content-end">
			<Button size="small" type="button" label="Keep" severity="secondary" @click="deleteOpen = false"></Button>
			<Button size="small" type="button" label="Delete" severity="danger" :disabled="saving" @click="deleteTask"></Button>
		</div>
	</Dialog>
	</div>
</template>
<script setup lang="ts">
import { InputGroup, InputGroupAddon, Button, Dialog, Toolbar, Select, Checkbox, InputText, Message, DataTable, Column, Tag, useToast } from "primevue"
import { MODES, type TaskRow } from "../components/SchedulerView"
import FormField from '@primevue/forms/formfield';
import AlCalendar from "../components/AlCalendar.vue"
import type { TimeRange } from "../components/AlCalendar.vue"
import { ref, onMounted, onBeforeUnmount, nextTick, computed } from "vue"
import { onBeforeRouteLeave } from "vue-router"
import { useConfirm } from "primevue/useconfirm"
import { ProgressBar } from "primevue"
import BasicForm, { type ValidateEventData } from "../components/BasicForm.vue"
import HelpToggle from "../components/HelpToggle.vue"
import { TriggerDefSchema } from "../components/ScheduleDefs"
import TimedTrigger from "../components/TimedTrigger.vue"
import { useSchedule } from "../composables/useSchedule"
import z from "zod";
const toast = useToast()
// the window shown, the timer tasks and their runs in it, the task in the dialog, with every call that loads or saves them
const {
	mode, offset, firstDay, dayCount, timeZone, eventList, documents, loading,
	editTarget, editModel, formKey, newTaskDocument, conflict, serverProblems, saving, hasUnsaved, canSave, values, stop, isStale, keepEditing,
	zoneNote, rangeText, rows, selectedPlugin, timerPlugins, pluginOptions,
	loadTimeline, start, setMode, move, goToday, checkDay,
	openTask, showTask, closeTask, newTask, saveTask, overwriteTask: overwrite, reloadTask: reload, deleteTask: remove,
} = useSchedule((severity, summary, detail) => toast.add({ severity, summary, detail, life: severity === "success" ? 3000 : 5000 }))
const API_URL = import.meta.env.VITE_API_URL
// the fields' help text, shown until hidden (for the page's life)
const showHelp = ref(true)

const bf = ref<InstanceType<typeof BasicForm>>()
const fieldNameWidth = "10rem";
const timeRange = ref<TimeRange>({start: 0, end: 1440, interval:30 })
const WEEKDAYS = (() => {
	const format = new Intl.DateTimeFormat("en-US", { weekday: "short", timeZone: "UTC" })
	return Array.from({ length: 7 }, (_, weekday) => format.format(new Date(Date.UTC(2023, 0, 1 + weekday))))
})()
const dialogOpen = ref(false)
const deleteOpen = ref(false)
const isTitleValid = ref(false)
const titleErrorMessage = ref<string|undefined>(undefined)
const isPluginValid = ref(false)
const pluginErrorMessage = ref<string|undefined>(undefined)

/** When a task runs, in the device's zone, as the timeline reads it (24 hours). */
function runText(when: Date): string {
	return new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: timeZone.value }).format(when).replace(",", "")
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
	return event.event.data.enabled ? "rgb(0,255,0)" : "rgb(180,180,180)"
}

let dayWatch: ReturnType<typeof setInterval>|undefined = undefined
onMounted(() => {
	start()
	// a page left open past midnight (in the device's zone) shows the new week
	dayWatch = setInterval(() => checkDay(), 60_000)
	window.addEventListener("beforeunload", warnBeforeClose)
})
onBeforeUnmount(() => {
	clearInterval(dayWatch)
	window.removeEventListener("beforeunload", warnBeforeClose)
	stop()
})

// --- the dialog's edits: closing it, leaving the page or closing the tab asks while they are not saved
const confirm = useConfirm()
const discardEdits = (): Promise<boolean> => {
	if(!dialogOpen.value || !hasUnsaved.value) return Promise.resolve(true)
	return new Promise(resolve => {
		confirm.require({
			header: "Unsaved changes",
			message: "Close the task and discard your changes?",
			icon: "mi mi-warning",
			acceptLabel: "Discard",
			rejectLabel: "Stay",
			accept: () => resolve(true),
			reject: () => resolve(false),
		})
	})
}
/** Close the dialog: nothing is being edited any more. */
function closeDialog() {
	dialogOpen.value = false
	closeTask()
}
/** The dialog's own close (its button, Escape) asks first when there are edits; Cancel is "close without saving" and does not. */
async function onDialogVisible(visible: boolean) {
	if(visible) return
	if(await discardEdits()) closeDialog()
}
onBeforeRouteLeave(async () => {
	if(!await discardEdits()) return false
	if(dialogOpen.value) closeDialog()
	return true
})
const warnBeforeClose = (e: BeforeUnloadEvent) => {
	if(dialogOpen.value && hasUnsaved.value) e.preventDefault()
}

// --- the dialog's form: the task's own fields around the plugin's
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
const onValidated = ({ result, values: held }: ValidateEventData) => {
	// the editor compares what the form holds with what it first reported for this task
	values(held, result.success)
	if(result.success) {
		isTitleValid.value = true
		titleErrorMessage.value = undefined
		return;
	}
	else {
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
/** A plugin field's problem from the server shows on that field: how many the form could show. */
const showOnField = (errors: { path: unknown[], message: string }[]) => bf.value?.setServerErrors(errors) ?? 0

const handleEventClick = (_event: any, _day: any, event: any) => {
	const staged = openTask(event.event.data)
	if(!staged) return
	dialogOpen.value = true
	nextTick().then(_ => showTask(staged))
}
function openRow(row: TaskRow) {
	handleEventClick(null, null, { event: { data: row.data } })
}
const handleNew = () => {
	if(newTask()) dialogOpen.value = true
}
/** A save that went through closes the dialog on the schedule as it is now. */
async function saved(done: Promise<boolean>) {
	if(!await done) return
	closeDialog()
	await loadTimeline()
}
const submitForm = ({ result }: { result?: { success: boolean, data?: Record<string, any> } }) => {
	if(!result?.success || !result.data || !editTarget.value) return
	// the fields the page adds around the plugin's own (see beforeFieldsSchema) are the task's; the rest is its content
	const { title, enabled, plugin_name, trigger, ...content } = result.data
	saved(saveTask({ title, enabled, trigger, task: { plugin_name, content } }, showOnField))
}
function overwriteTask() {
	saved(overwrite(showOnField))
}
/** Someone else changed the task: take their version; when it cannot be read, the dialog closes on a fresh schedule. */
async function reloadTask() {
	if(await reload()) return
	closeDialog()
	await loadTimeline()
}
async function deleteTask() {
	const outcome = await remove()
	deleteOpen.value = false
	if(outcome !== "done") return
	closeDialog()
	await loadTimeline()
}
// a stored task can be saved once it differs from what the form first showed (defaults included); a new task has nothing to compare with
const unchanged = computed(() => !!editTarget.value?.id && !hasUnsaved.value)
const saveTitle = computed(() => unchanged.value ? "Nothing changed yet" : "Save the task")

/** Close the dialog without saving: the edits are dropped (the next one starts from the stored task). */
const handleCancel = () => {
	closeDialog()
}
const handleSubmit = () => {
	bf.value?.submit()
}
</script>
<style scoped>
.trigger-heading {
	margin-top: .5rem;
	font-weight: bold;
}
/* the page area is the window under the toolbar: the calendar takes what the toolbar leaves and only its hours scroll (one scrollbar) */
.scheduler {
	overflow: hidden;
}
.calendar {
	flex: 1 1 0;
	min-height: 0;
}
.task-list {
	flex: 1 1 0;
	min-height: 0;
	display: flex;
	flex-direction: column;
	/* the panel's surface under the rows too, not the page */
	background: var(--p-content-background);
}
.task-table {
	flex: 1 1 0;
	min-height: 0;
}
.task-title {
	padding: 0;
}
.scheduler-actions {
	width: auto;
}
.range-label {
	font-weight: bold;
}
.day-header {
	display: flex;
	align-items: center;
	justify-content: center;
	font-weight: bold;
	background-color: var(--p-content-hover-background);
	border-bottom: 1px solid var(--p-content-border-color);
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
/* on a phone a week is seven narrow columns: the weekday under the day, smaller; the toolbar's buttons that have a glyph show only that */
@media (max-width: 40rem) {
	.day-header > div {
		display: flex;
		flex-direction: column;
		align-items: center;
	}
	.day-header-day {
		font-size: 1.2rem;
	}
	.day-header-dow {
		font-size: .8rem;
		margin-left: 0;
	}
	.short-on-phone :deep(.p-button-label) {
		display: none;
	}
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
	color: var(--p-text-muted-color);
	border-top: 1px dashed var(--p-content-border-color);
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
	font-size: .9rem;
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
