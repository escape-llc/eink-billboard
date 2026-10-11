/**
 * What a track says about itself in the playlist editor: the descriptor's `describe` template filled from the track's content.
 * `describe` is our own descriptor keyword (a plugin's or a data source's, beside `name`): text with `{field}` placeholders, each a field of its
 * `instanceSettings`. A field that is not set (missing, null, "", false, an empty list) drops out, with the word next to it that only joined it.
 * A `schema` field (the chosen data source) reads as that source's own description, so a Slide Show over the comic XKCD says "Comic XKCD".
 */
import type { PluginDef } from "./ScheduleDefs"

export type Describable = { id: string, name: string, describe?: string, instanceSettings?: { schema?: { properties?: { name: string, type?: string }[] } } | null }

const MAX_PART = 40

function clip(text: string): string {
	return text.length <= MAX_PART ? text : `${text.slice(0, MAX_PART - 1)}…`
}

/** The text of one value, or "" when it says nothing. */
function say(value: unknown): string {
	if (value === null || value === undefined || value === false || value === "") return ""
	if (Array.isArray(value)) return value.map(say).filter(Boolean).join(", ")
	if (typeof value === "object") return ""
	return clip(String(value).trim())
}

export function describeItem(item: Describable, content: Record<string, any>, sources: Describable[] = [], depth = 0): string {
	const template = item.describe
	if (!template) return item.name
	const types = new Map((item.instanceSettings?.schema?.properties ?? []).map(p => [p.name, p.type]))
	const text = template.replace(/\{([A-Za-z0-9_]+)\}/g, (_all, name: string) => {
		const value = content?.[name]
		if (types.get(name) === "schema") {
			const source = sources.find(s => s.id === value)
			// a data source is described by its own template; one that is gone is still named by its id
			return source && depth < 2 ? describeItem(source, content, sources, depth + 1) : say(value)
		}
		return say(value)
	})
	return text.replace(/\s+/g, " ").replace(/\s+([,.:])/g, "$1").trim() || item.name
}

/** A playlist track: the plugin's description of it, or the plugin's name (or nothing, for a plugin that is gone). */
export function describeTrack(plugin: PluginDef | undefined, content: Record<string, any>, sources: Describable[]): string | null {
	return plugin ? describeItem(plugin as Describable, content, sources) : null
}
