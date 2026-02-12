export const PLAYLIST_SCHEMA = "urn:inky:storage:schedule:playlist:1"
export const TIMED_SCHEDULE_SCHEMA = "urn:inky:storage:schedule:timed:1"
export type PlaylistItem = {
	id: string;
	type: string;
	plugin_name: string;
	title: string;
	content: Record<string, any>;
}
export type PlaylistSchedule = {
	_schema: string;
	id: string;
	name: string;
	items: PlaylistItem[];
}
export type TriggerDays = {
	type: "dayofweek" | "dayofmonth";
	days: number[];
}
export type TriggerDayAndMonth = {
	type: "dayandmonth";
	month: number;
	day: number;
}
export type TriggerHours = {
	type: "hourofday" | "dayofmonth";
	hours: number[];
	minutes: number[];
}
export type TriggerTimeSpecific = {
	type: "specific";
	hour: number;
	minute: number;
}
export type TriggerHourly = {
	type: "hourly";
	minutes: number[];
}
export type DayTrigger = TriggerDays | TriggerDayAndMonth
export type TimeTrigger = TriggerHours | TriggerTimeSpecific | TriggerHourly
export type TriggerDef = {
	on_startup: boolean;
	day: DayTrigger;
	time: TimeTrigger;
}
export type TimedScheduleTask = {
	plugin_name: string;
	title: string;
	content: Record<string, any>;
}
export type TimedScheduleItem = {
	id: string;
	name: string;
	enabled: boolean;
	description: string;
	task: TimedScheduleTask;
	trigger: TriggerDef;
}
export type TimedSchedule = {
	_schema: string;
	id: string;
	name: string;
	items: TimedScheduleItem[];
}
export type ScheduleDef = PlaylistSchedule | TimedSchedule