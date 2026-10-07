<template>
	<div class="scheduler-container" :style="{ '--time-column-rows': slotTotal, '--date-row-columns': daysInRange.length }">
		<div class="day-header-container grid-horizontal">
			<template v-for="day in daysInRange" :key="day.key">
				<slot name="dayheader" :day="day">
					<div :style="{'grid-column': day.column, 'grid-row': day.row }">
						<div>
							<span>{{ day.dayOfMonth }}</span>
							<span>{{ weekdayName(day.weekday) }}</span>
						</div>
					</div>
				</slot>
			</template>
		</div>
		<div class="events-panel-scroll" style="align-self: stretch;">
			<div class="events-panel grid-horizontal grid-vertical">
				<template v-for="time in timesInRange" :key="time.index">
					<slot name="timeheader" :time="time">
						<div :style="{'grid-row':time.row,'grid-column':time.column}">
							<div>
								<span>{{ twoDigits(time.hour) }}</span>
								<span>{{ twoDigits(time.minute) }}</span>
							</div>
						</div>
					</slot>
				</template>
				<template v-for="(day,ix) in daysInRange" :key="day.key">
					<div class="event-grid-track grid-vertical" :style="{'grid-column': ix + 2, 'grid-row': '1 / span var(--time-column-rows)'}">
						<template v-for="time in timesInRange" :key="time.index">
							<div class="event-grid-track-cell" :style="{'grid-row':time.row,'grid-column':`${time.column}`}"></div>
						</template>
					</div>
					<div class="event-track grid-vertical" style="background: transparent" :style="{'grid-column': ix + 2, 'grid-row': '1 / span var(--time-column-rows)'}">
						<template v-for="event in eventsOf(day.key)" :key="`${event.index}-${event.continued}`">
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
import { computed, onBeforeUnmount, ref } from "vue"
import { dayInfo, daysFrom, place, segments, slotCount, timeSlots, zonedParts, type TimeRange } from "./CalendarTime"

export type { TimeRange }
export type DailyInfo = {
	/** `YYYY-MM-DD` */
	key: string
	/** a Date whose local fields are this calendar day */
	date: Date
	/** 0 = Sunday */
	weekday: number
	dayOfMonth: number
	/** it is today in the calendar's time zone (kept current while the page is open) */
	today: boolean
	index: number
	column: number
	row: number
}
export type TimeSlotInfo = {
	/** minutes since midnight */
	minutes: number
	hour: number
	minute: number
	index: number
	column: number
	row: number
}
export type EventCellInfo = {
	date: Date
	/** when the event starts (the whole event, also on the day it continues) */
	start: Date
	index: number
	column: number
	row: number
	span: number
	/** this part continues an event that began on the day before */
	continued: boolean
	event: EventInfo
}
export interface EventInfo {
	start: Date
	/** minutes */
	duration: number
	title: string
	data?: unknown
}
export type PropsType = {
	/** the first day shown, `YYYY-MM-DD` */
	firstDay: string
	dayCount: number
	/** the zone the days and times are read in (an IANA name or a fixed offset such as `+05:30`); the browser's when not given */
	timeZone?: string
	timeRange: TimeRange
	eventList: EventInfo[]
}
const props = defineProps<PropsType>()

// the weekday names are one formatter, made once (the labels are static text per weekday)
const WEEKDAYS = (() => {
	const format = new Intl.DateTimeFormat("en-US", { weekday: "short", timeZone: "UTC" })
	return Array.from({ length: 7 }, (_, weekday) => format.format(new Date(Date.UTC(2023, 0, 1 + weekday))))
})()
const weekdayName = (weekday: number) => WEEKDAYS[weekday] ?? ""
const twoDigits = (value: number) => String(value).padStart(2, "0")

// "today" moves on while the page is open
const clock = ref(new Date())
const ticker = setInterval(() => { clock.value = new Date() }, 30_000)
onBeforeUnmount(() => clearInterval(ticker))
const todayKey = computed(() => zonedParts(clock.value, props.timeZone).key)

const slotTotal = computed(() => slotCount(props.timeRange))
const timesInRange = computed<TimeSlotInfo[]>(() => timeSlots(props.timeRange).map(slot => ({ ...slot, column: 1 })))
const daysInRange = computed<DailyInfo[]>(() => daysFrom(props.firstDay, props.dayCount).map((key, index) => ({
	key, ...dayInfo(key), today: key === todayKey.value, index, column: index + 2, row: 1
})))

// each event is drawn on every day it touches, in the slot its start falls in
const cellsByDay = computed(() => {
	const days = new Map<string, EventCellInfo[]>()
	props.eventList.forEach((event, index) => {
		const { key, minutes } = zonedParts(event.start, props.timeZone)
		for(const segment of segments(key, minutes, event.duration)) {
			const spot = place(segment, props.timeRange)
			if(!spot) continue
			const cell: EventCellInfo = {
				date: dayInfo(segment.day).date, start: event.start, index, column: 1,
				row: spot.row, span: spot.span, continued: segment.continued, event
			}
			const list = days.get(segment.day)
			if(list) list.push(cell)
			else days.set(segment.day, [cell])
		}
	})
	return days
})
const eventsOf = (key: string): EventCellInfo[] => cellsByDay.value.get(key) ?? []
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