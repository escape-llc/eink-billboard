<template>
	<div class="flex flex-column" style="height:80vh;width:100%;justify-items: stretch;align-items: stretch;">
	<Toolbar class="p-0">
		<template #start>
			<div style="font-size:150%">Scheduler</div>
		</template>
		<template #center>
			<Select v-model:="eventList" />
		</template>
	</Toolbar>
	<AlCalendar style="width:100%" class="calendar" :dateRange="dateRange" :timeRange="timeRange" :eventList="eventList">
		<template #dayheader="{ day }">
			<div class="day-header" :style="{'grid-column': day.column, 'grid-row': day.row }"
				:class="{'day-header-weekend': day.date.getDay() === 0 || day.date.getDay() === 6, 'day-header-today': isToday(day.date) }">
				<div>
					<span class="day-header-day">{{ day.date.getDate() }}</span>
					<span class="day-header-dow">{{ new Intl.DateTimeFormat("en-US", {weekday:'short'}).format(day.date) }}</span>
				</div>
			</div>
		</template>
		<template #timeheader="{ time }">
			<div class="time-header" :style="{'grid-row':time.row,'grid-column':time.column}">
				<div>
					<span v-if="time.date.getMinutes() === 0" class="time-header-hour">{{ new Intl.DateTimeFormat("en-US", {timeZone:"GMT",hour12: false, hour:'2-digit'}).format(time.date) }}</span>
					<span class="time-header-minute">{{ new Intl.DateTimeFormat("en-US", {hour12: false, minute:'2-digit'}).format(time.date).padStart(2, '0') }}</span>
				</div>
			</div>
		</template>
		<template #event="{ day, event }">
			<div class="event"
				:style="{'grid-row': `${event.row} / span ${event.span}`, 'background-color': derefColor(event), 'border-left': `5px solid color-mix(in srgb, ${sidebarColor(event)} 80%, #333 20%)`}"
				@click="handleEventClick($event, day, event)">
				<div class="event-title">{{ event.event.title }}</div>
			</div>
		</template>
	</AlCalendar>
	<Dialog v-model:visible="dialogOpen" model header="Edit Item" style="width:60%; font-size:90%">
		<BasicForm v-if="selectedPlugin" ref="bf" :form="selectedPlugin.instanceSettings" :initialValues="editModel.content" :baseUrl="API_URL"
			:beforeFieldsSchema="beforeFieldsSchema" :addInitialValues="addInitialValues"
			@validate="onValidated"
			class="form">
			<template #header>
				<Toolbar style="width:100%" class="p-1 mt-2">
					<template #start>
						<div style="font-weight: bold;font-size:150%">Item Settings</div>
					</template>
					<template #end>
						<InputGroup>
							<Button size="small" icon="pi pi-check" severity="success" :disabled="!editModelValid" @click="handleSubmit" />
							<Button size="small" icon="pi pi-times" severity="danger" @click="handleReset" />
						</InputGroup>
					</template>
				</Toolbar>
			</template>
			<template #group-header="slotProps">
				<h3 class="mb-0">{{ slotProps.label }}</h3>
			</template>
			<template #before-fields>
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
							<TimedTrigger :modelValue="$field.value" parentPropName="trigger." :fieldNameWidth="fieldNameWidth" @change="$field.onChange" />
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
		<div class="flex gap-2 pt-2" style="justify-self:flex-end">
				<Button type="button" label="Cancel" severity="secondary" @click="dialogOpen = false"></Button>
				<Button type="button" label="Save" @click="dialogOpen = false"></Button>
		</div>
	</Dialog>
	</div>
</template>
<script setup lang="ts">
import { InputGroup, InputGroupAddon, Button, Dialog, Toolbar, Select, Checkbox, InputText, Message } from "primevue"
import FormField from '@primevue/forms/formfield';
import AlCalendar from "../components/AlCalendar.vue"
import type { DateRange, TimeRange, EventInfo } from "../components/AlCalendar.vue"
import { MS_PER_DAY } from "../components/DateUtils"
import { ref, onMounted, nextTick, toRaw, provide, computed } from "vue"
import BasicForm, { type ValidateEventData } from "../components/BasicForm.vue"
import type { FormDef } from "../components/FormDefs"
import type { PluginDef } from "../components/ScheduleDefs"
import { TriggerDefSchema } from "../components/ScheduleDefs"
import TimedTrigger from "../components/TimedTrigger.vue"
import z from "zod";

const bf = ref<InstanceType<typeof BasicForm>>()
const fieldNameWidth = "10rem";
const form = ref<FormDef>()
const now = new Date()
const dateRange = ref<DateRange>({ start:new Date(now), end:new Date(now.getTime() + 6*MS_PER_DAY) })
const timeRange = ref<TimeRange>({start: 0, end: 1440, interval:30 })
const eventList = ref<EventInfo[]>([])
const dialogOpen = ref(false)
const currentEvent = ref()

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
const pluginOptions = computed<DropdownOption[]>(() => pluginList.value.map(p => ({ id: p.id, name: p.name })))

function isToday(someDate:Date):boolean {
  const today = new Date(now);
  today.setHours(0, 0, 0, 0);
  const dateToCompare = new Date(someDate);
  dateToCompare.setHours(0, 0, 0, 0);
  return dateToCompare.getTime() === today.getTime();
}
function derefSchedule(schedules:Record<string,any>, sid:string, id:string) {
	if(sid in schedules) {
		const schedule = schedules[sid]
		const item = schedule.items.find(sx => sx.id === id)
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


onMounted(() => {
	const renderUrl = `${API_URL}api/schedule/tasks/render`
	const listPluginsUrl = `${API_URL}api/plugins/list`
	const listDatasourcesUrl = `${API_URL}api/datasources/list`
	const pxs = [
		fetch(renderUrl).then(rx => rx.json()),
		fetch(listPluginsUrl).then(rx => rx.json()),
		fetch(listDatasourcesUrl).then(rx => rx.json()),
	]
	Promise.all(pxs).then(rxs => {
		console.log("yay", rxs)
		const json = rxs[0]
		pluginList.value = rxs[1]
		dataSources.value = rxs[2]
		if(json.success) {
			json.start_ts = new Date(json.start_ts)
			json.end_ts = new Date(json.end_ts)
			const events:EventInfo[] = []
			json.render.forEach(rx => {
				rx.start = new Date(rx.scheduled_time)
				rx.end = new Date(rx.start.getTime() + 30*60*1000)
//				console.log("item", rx)
				const sref = derefSchedule(json.schedules, rx.schedule, rx.id)
//				console.log("ref", ref)
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
					ei.data = sref
				}
				events.push(ei)
			})
			eventList.value = events
		}
	})
	.catch(ex => {
		console.error("render.unhandled", ex)
	})
})
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
	console.log("addInitialValues", ox)
	return ox
}
const onValidated = ({ result, values }: ValidateEventData) => {
	console.log("onValidated", result, values)
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
const handleEventClick = ($event, day, event) => {
	console.log("handleEventClick", day, event)
	if(pluginList.value.length > 0) {
		console.log("edit item", pluginList.value)
		dialogOpen.value = true
		currentEvent.value = event
		const target = pluginList.value.find(px => px.id === event.event.data.task.plugin_name)
		if(target) {
			form.value = structuredClone(toRaw(target.instanceSettings))
			nextTick().then(_ => {
				//initialValues.value = structuredClone(toRaw(event.event.data.task.content))
				const evx = structuredClone(toRaw(event.event.data))
				console.log("ready2edit", evx)
				const stage = {
					id: evx.id,
					title: evx.title,
					enabled: evx.enabled,
					trigger: evx.trigger,
					plugin_name: evx.task.plugin_name,
					content: evx.task.content
				}
				editModel.value = stage
			})
		}
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