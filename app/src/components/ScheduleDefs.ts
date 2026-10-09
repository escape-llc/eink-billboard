import { z } from 'zod'
import type { FormDef } from './FormDefs'

/** A plugin's descriptor as `/api/plugins/list` sends it (plugin-info.json). */
export type PluginDef = {
	id: string
	name: string
	version?: string
	description?: string
	disabled?: boolean
	color?: string
	/** what the plugin does: layer-background, layer-foreground (playlist), layer-priority, layer-overlay (timer), media-* (what it takes) */
	features?: string[]
	/** the plugin's own settings (none for most) */
	settings?: FormDef | null
	/** the settings of one use of the plugin: the form of a track or timer task */
	instanceSettings: FormDef
}

export const PLAYLIST_SCHEMA = "urn:inky:storage:schedule:playlist:1"
export const TIMED_SCHEDULE_SCHEMA = "urn:inky:storage:schedule:tasks:1"
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
// day triggers
export type TriggerDays = {
	type: "dayofweek" | "dayofmonth";
	days: number[];
}
export type TriggerDayAndMonth = {
	type: "dayandmonth";
	month: number;
	day: number;
}
// time triggers
export type TriggerHourly = {
	type: "hourly";
	minutes: number[];
}
export type TriggerHours = {
	type: "hourofday";
	hours: number[];
	minutes: number[];
}
export type TriggerTimeSpecific = {
	type: "specific";
	hour: number;
	minute: number;
}
export type DayTrigger = TriggerDays | TriggerDayAndMonth
export type TimeTrigger = TriggerHours | TriggerTimeSpecific | TriggerHourly
export type TriggerDef = {
	on_startup: boolean;
	day: DayTrigger;
	time: TimeTrigger;
}
export type TimerTaskTask = {
	plugin_name: string;
	content: Record<string, any>;
}
export type TimerTaskItem = {
	id: string;
	enabled: boolean;
	title: string;
	task: TimerTaskTask;
	trigger: TriggerDef;
}
export type TimerTasks = {
	_schema: string;
	id: string;
	name: string;
	items: TimerTaskItem[];
}
export type ScheduleDef = PlaylistSchedule | TimerTasks

// Zod Schemas
export const TriggerDefSchema = z.object({
	on_startup: z.boolean(),
	day: z.object({
		type: z.string(),
		days: z.array(z.number()).optional(),
		month: z.number().optional(),
		day: z.number().optional(),
	}).superRefine((data, ctx) => {
		if (data.type === "dayofweek" || data.type === "dayofmonth") {
			if (!data.days || data.days.length === 0) {
				ctx.addIssue({
					code: "custom",
					message: "At least one day must be selected",
					path: ["days"]
				});
			}
		} else if (data.type === "dayandmonth") {
			if (data.month === undefined) {
				ctx.addIssue({
					code: "custom",
					message: "Month must be specified",
					path: ["month"]
				});
			}
			if (data.day === undefined) {
				ctx.addIssue({
					code: "custom",
					message: "Day must be specified",
					path: ["day"]
				});
			}
		} else {
			ctx.addIssue({
				code: "custom",
				message: "Invalid day trigger type",
				path: ["type"]
			});
		}
	}),
	time: z.object({
		type: z.string(),
		minutes: z.array(z.number()).optional(),
		hours: z.array(z.number()).optional(),
		hour: z.number().optional(),
		minute: z.number().optional(),
	}).superRefine((data, ctx) => {
		if (data.type === "hourly") {
			if (!data.minutes || data.minutes.length === 0) {
				ctx.addIssue({
					code: "custom",
					message: "At least one minute must be selected",
					path: ["minutes"]
				});
			}
		} else if (data.type === "hourofday") {
			if (!data.hours || data.hours.length === 0) {
				ctx.addIssue({
					code: "custom",
					message: "At least one hour must be selected",
					path: ["hours"]
				});
			}
			if (!data.minutes || data.minutes.length === 0) {
				ctx.addIssue({
					code: "custom",
					message: "At least one minute must be selected",
					path: ["minutes"]
				});
			}
		} else if (data.type === "specific") {
			if (data.hour === undefined) {
				ctx.addIssue({
					code: "custom",
					message: "Hour must be specified",
					path: ["hour"]
				});
			}
			if (data.minute === undefined) {
				ctx.addIssue({
					code: "custom",
					message: "Minute must be specified",
					path: ["minute"]
				});
			}
		} else {
			ctx.addIssue({
				code: "custom",
				message: "Invalid time trigger type",
				path: ["type"]
			});
		}
	}),
})