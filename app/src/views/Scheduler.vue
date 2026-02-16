<template>
	<div class="flex flex-column" style="height:80vh;width:100%;justify-items: stretch;align-items: stretch;">
	<Toolbar class="p-0">
		<template #start>
			<div style="font-size:150%">Scheduler</div>
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
		<template #event="{ day, event}">
			<div class="event"
				:style="{'grid-row': `${event.row} / span ${event.span}`, 'background-color': derefColor(event), 'border-left': `5px solid color-mix(in srgb, ${derefColor(event)} 80%, #333 20%)`}"
				@click="handleEventClick($event, day, event)">
				<div>{{ event.event.title }}</div>
			</div>
		</template>
	</AlCalendar>
	<Dialog v-model:visible="dialogOpen" model header="Edit Item" style="width:50%">
		<BasicForm :form="form" :initialValues :baseUrl="API_URL" class="form">
			<template #header>
				<Toolbar style="width:100%" class="p-1 mt-2">
					<template #start>
						<div style="font-weight: bold;font-size:150%">Item Settings</div>
					</template>
					<template #end>
						<InputGroup>
							<Button size="small" icon="pi pi-check" severity="success" />
							<Button size="small" icon="pi pi-times" severity="danger" />
						</InputGroup>
					</template>
				</Toolbar>
			</template>
			<template #group-header="slotProps">
				<h3 class="mb-0">{{ slotProps.label }}</h3>
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
import { InputGroup, Button, Dialog, Toolbar } from "primevue"
import AlCalendar from "../components/AlCalendar.vue"
import type { DateRange, TimeRange, EventInfo } from "../components/AlCalendar.vue"
import { MS_PER_DAY } from "../components/DateUtils"
import { ref, onMounted, nextTick } from "vue"
import BasicForm from "../components/BasicForm.vue"
import type {FormDef} from "../components/FormDefs"

const form = ref<FormDef>()
const initialValues = ref()
const now = new Date()
const dateRange = ref<DateRange>({ start:new Date(now), end:new Date(now.getTime() + 6*MS_PER_DAY) })
const timeRange = ref<TimeRange>({start: 0, end: 1440, interval:30 })
const eventList = ref<EventInfo[]>([])
const dialogOpen = ref(false)
const currentEvent = ref()

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
function derefColor(event:any):string {
	switch(event.event.data.plugin_name) {
		case "clock": return "#ffeedd"
		case "wpotd": return "#eeffdd"
		case "newspaper": return "#ddffee"
		case "image-folder": return "#ffddee"
		case "ai-image": return "#eeddff"
	}
	return "#ddeeff";
}
const API_URL = import.meta.env.VITE_API_URL
let pluginList:any = undefined

onMounted(() => {
	const renderUrl = `${API_URL}api/schedule/tasks/render`
	const listUrl = `${API_URL}api/plugins/list`
	const pxs = [
	fetch(renderUrl).then(rx => rx.json()),
	fetch(listUrl).then(rx => rx.json()),
]
	Promise.all(pxs).then(rxs => {
		console.log("yay", rxs)
		const json = rxs[0]
		pluginList = rxs[1]
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
					ei.title = `${sref.task.title} (${sref.task.plugin_name})`
					ei.duration = sref.task.content.durationMinutes
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
const handleEventClick = ($event, day, event) => {
	console.log("handleEventClick", day, event)
	if(pluginList) {
		console.log("edit item", pluginList)
		dialogOpen.value = true
		currentEvent.value = event
		const target = pluginList.find(px => px.id === event.event.data.plugin_name)
		if(target) {
			form.value = target.instanceSettings
			nextTick().then(_ => {
				initialValues.value = event.event.data.content
			})
		}
	}
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
</style>
<style>
:root {
	--calendar-height: 800px;
}
</style>