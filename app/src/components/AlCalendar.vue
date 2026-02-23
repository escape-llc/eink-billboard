<template>
	<div class="scheduler-container">
		<div class="day-header-container grid-horizontal">
			<template v-for="day in daysInRange">
				<slot name="dayheader" :day="day">
					<div :style="{'grid-column': day.column, 'grid-row': day.row }">
						<div>
							<span>{{ day.date.getDate() }}</span>
							<span>{{ new Intl.DateTimeFormat("en-US", {weekday:'short'}).format(day.date) }}</span>
						</div>
					</div>
				</slot>
			</template>
		</div>
		<div class="events-panel-scroll" style="align-self: stretch;">
			<div class="events-panel grid-horizontal grid-vertical">
				<template v-for="time in timesInRange">
					<slot name="timeheader" :time="time">
						<div :style="{'grid-row':time.row,'grid-column':time.column}">
							<div>
								<span>{{ new Intl.DateTimeFormat("en-US", {timeZone:"GMT",hour12: false, hour:'2-digit'}).format(time.date) }}</span>
								<span>{{ new Intl.DateTimeFormat("en-US", {hour12: false, minute:'2-digit'}).format(time.date).padStart(2, '0') }}</span>
							</div>
						</div>
					</slot>
				</template>
				<template v-for="(day,ix) in daysInRange">
					<div class="event-grid-track grid-vertical" :style="{'grid-column': ix + 2, 'grid-row': '1 / span var(--time-column-rows)'}">
						<template v-for="time in timesInRange">
							<div class="event-grid-track-cell" :style="{'grid-row':time.row,'grid-column':`${time.column}`}"></div>
						</template>
					</div>
					<div class="event-track grid-vertical" style="background: transparent" :style="{'grid-column': ix + 2, 'grid-row': '1 / span var(--time-column-rows)'}">
						<template v-for="event in filterEvents(day)">
							<slot name="event" :day="day" :event="event">
								<div class="default-event" :style="{'grid-row': `${event.row} / span ${event.span}`}">
									<div>{{ event.event.title }}</div>
								</div>
							</slot>
						</template>
					</div>
				</template>
			</div>
		</div>
	</div>
</template>
<script lang="ts" setup>
import { ref, computed, watch } from "vue"
import { DateBuilder, MS_PER_DAY } from "./DateUtils"

export type DateRange = {
	start: Date
	end: Date
}
export type TimeRange = {
	start: number;
	end: number;
	interval: number;
}
export type DailyInfo = {
	date: Date
	index: number
	column: number
	row: number
}
export type EventCellInfo = {
	date: Date
	start: Date
	end: Date
	index: number
	column: number
	row: number
	span: number
	event: EventInfo
}
export interface EventInfo {
	start: Date
	duration: number
	title: string
	data?: unknown
}
export type PropsType = {
	dateRange: DateRange
	timeRange: TimeRange
	eventList: EventInfo[]
}
const timeSlots = computed(() => {
	const ts = props.timeRange;
	return Math.round((ts.end - ts.start)/ts.interval);
})
function filterEvents(day: DailyInfo): EventCellInfo[] {
	const filtered:EventCellInfo[] = [];
	let index = 0
	console.log("filterEvents", day);
	props.eventList.forEach(ev => {
		const start = new DateBuilder(ev.start).midnight().date()
//		console.log("filterEvents", ev, start, start.getTime(), day.date.getTime());
		if(start.getTime() === day.date.getTime()) {
			const end = new DateBuilder(ev.start).minutes(ev.duration).date()
			const offset_sec = (ev.start.getTime() - day.date.getTime())/1000
			const offset_min = offset_sec/60;
			const row = Math.round(offset_min/props.timeRange.interval)
//			console.log("filterEvents.hit", ev.start, end, offset_min, props.timeRange.interval, row)
			filtered.push({
				date: start,
				start: ev.start,
				end: end,
				column: 1,
				row: Math.min(timeSlots.value, Math.max(1, row + 1)),
				span: Math.max(1, Math.round(ev.duration/props.timeRange.interval)),
				index, event: ev
			})
			index += 1
		}
	})
	filtered.length && console.log("filterEvents", filtered);
	return filtered;
}
const props = defineProps<PropsType>()
const timesInRange = computed(() => {
	let offset = 0
	let index = 0
	let row = 1
	const days: DailyInfo[] = [];
	while(offset < props.timeRange.end) {
		let current = new DateBuilder(new Date(0)).minutes(props.timeRange.start + offset).date()
		days.push({date: new Date(current.getTime()), index, column: 1, row })
		offset += props.timeRange.interval
		index += 1
		row += 1
	}
	return days;
})
const daysInRange = computed(() => {
	let start = new DateBuilder(props.dateRange.start).midnight().date();
	let end = new DateBuilder(props.dateRange.end).midnight().date();
	console.log("daysInRange", start, end);
	const days: DailyInfo[] = [];
	let index = 0;
	let column = 2;
	while(start.getTime() <= end.getTime()) {
		days.push({date: new Date(start.getTime()), index, column, row: 1 })
		start.setTime(start.getTime() + MS_PER_DAY);
		index += 1;
		column += 1;
	}
	console.log("daysInRange", days);
	return days;
})
watch(props.dateRange, (nv,ov) => {
	console.log("dateRange", nv, ov);
	if(nv) {
	}
})
</script>
<style scoped>
.scheduler-container {
	display: flex;
	flex-direction: column;
	margin: auto;
}
.grid-horizontal {
	grid-template-columns: var(--time-column-width) repeat(var(--date-row-columns), 1fr);
	column-gap: var(--grid-column-gap);
}
.grid-vertical {
	grid-template-rows: repeat(var(--time-column-rows), var(--time-column-height));
}
.day-header-container {
	display: grid;
	grid-row: 1;
	margin-right: 16px;
}
.events-panel-scroll {
	grid-row: 2;
	overflow-y: auto;
	scrollbar-gutter: stable;
}
.events-panel {
	display: grid;
	padding-top: var(--events-panel-padding-vertical);
	padding-bottom: var(--events-panel-padding-vertical);
	background-color: var(--events-panel-background-color);
}
.event-grid-track {
	display: grid;
	background-color: var(--grid-track-background-color);
	border-radius:4px;
	width: 100%;
	z-index: 1;
}
.event-grid-track-cell {
	border-top: 1px dashed var(--grid-track-cell-color);
	opacity: .2;
}
.event-track {
	display: grid;
	background-color: transparent;
	width: 100%;
	z-index: 10;
}
.default-event {
	border-radius:4px;
	border: 1px solid black;
	margin: .1rem .2rem;
	padding: .2rem .4rem;
	text-overflow: ellipsis;
	overflow: hidden;
	border-left: 5px solid black;
	box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}
</style>
<style>
:root {
	--events-panel-background-color: silver;
	--events-panel-padding-vertical: 1rem;
	--grid-column-gap: 2px;
	--grid-track-background-color: gray;
	--grid-track-cell-color: #eee;
	--time-column-rows: 48;
	--date-row-columns: 7;
	--time-column-height: 2rem;
	--time-column-width: 4rem;
}
</style>