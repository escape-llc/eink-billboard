<template>
	<!-- a plugin's or data source's descriptor, one attribute to a row: what it is called, what it needs and what it can do (the Plugins and the Data Sources tabs both show it) -->
	<dl class="item-info" data-testid="item-info">
		<template v-for="row in rows" :key="row.label">
			<dt>{{ row.label }}</dt>
			<dd :data-testid="`info-${row.label.toLowerCase().replace(/ /g, '-')}`">
				<template v-if="row.kind === 'tags'">
					<span v-if="!row.tags.length" class="none">none</span>
					<Tag v-for="tag in row.tags" :key="tag" class="tag" :value="tag" :title="FEATURE_HELP[tag]" severity="secondary" />
				</template>
				<i v-else-if="row.kind === 'flag'" class="mi" :class="row.value ? 'mi-check' : 'mi-close'" role="img" :aria-label="row.value ? 'yes' : 'no'"></i>
				<template v-else>{{ row.value }}</template>
			</dd>
		</template>
	</dl>
</template>
<script setup lang="ts">
import { computed } from "vue"
import { Tag } from "primevue"

/** What a descriptor says about a plugin or a data source (`*-info.json`), as the settings routes list it. */
export interface ItemDef {
	id: string
	name?: string
	version?: string
	description?: string
	describe?: string
	disabled?: boolean
	features?: string[]
	/** data sources only: the other data sources it asks for their data */
	uses?: string[]
	/** data sources only: the capabilities (`data-*` features) it needs, which any provider of them supplies */
	requires?: string[]
	/** data sources only: its list outlasts a visit, and the plugin that shows it keeps it */
	keepsList?: boolean
}
const props = defineProps<{ item: ItemDef, kind: "plugin" | "datasource" | "provider", usedBy?: string[] }>()

/** What each feature word means, as a tooltip: the words are the vocabulary a plugin and a data source agree on. */
const FEATURE_HELP: Record<string, string> = {
	"internet": "Downloads from the internet.",
	"filesystem": "Reads files of the device.",
	"api": "Data only: other data sources ask it for its data (it draws nothing, and no plugin offers it).",
	"api-client": "Asks an API data source for its data (see Uses); that one does the downloading.",
	"api-key": "Needs an API key, which is set in its settings.",
	"paid-service": "Each use is paid for with the provider.",
	"ai-provider": "An AI provider: it holds the key and the model list its text and image parts use.",
	"data-weather": "Supplies the weather: any page or overlay that needs a weather provider can use it.",
	"data-calendar": "Supplies calendar events: any page or overlay that needs a calendar provider can use it.",
	"data-ai-text": "An AI text part: writes text for a generator.",
	"data-ai-image": "An AI image part: draws a picture for a generator.",
	"data-transit": "Transit: the departures and alerts of a stop, for the transit pages.",
	"layer-background": "Can be shown as the playlist's background page.",
	"layer-foreground": "Can be shown over the background, as a page of its own that nothing hides.",
	"layer-priority": "Can be shown for a while over everything (a Priority Update).",
	"layer-overlay": "Can be drawn in a zone of the panel (an Overlay).",
	"media-image": "Makes (or shows) a single image.",
	"media-list": "Makes a list of images, shown one after another.",
}

type Row = { label: string, kind: "text", value: string } | { label: string, kind: "tags", tags: string[] } | { label: string, kind: "flag", value: boolean }
const rows = computed<Row[]>(() => {
	const item = props.item
	const list: Row[] = [
		{ label: "Name", kind: "text", value: item.name ?? item.id },
		{ label: "Id", kind: "text", value: item.id },
		{ label: "Version", kind: "text", value: item.version ?? "" },
		{ label: "Enabled", kind: "flag", value: !item.disabled },
		{ label: "Description", kind: "text", value: item.description ?? "" },
		{ label: "Features", kind: "tags", tags: item.features ?? [] },
	]
	if(props.kind === "provider") {
		// what it supplies (its capabilities), what it uses (a key holder), and who relies on it
		list.push({ label: "Supplies", kind: "tags", tags: (item.features ?? []).filter(f => f.startsWith("data-")) })
		list.push({ label: "Uses", kind: "tags", tags: item.uses ?? [] })
		list.push({ label: "Used by", kind: "tags", tags: props.usedBy ?? [] })
	}
	else if(props.kind === "datasource") {
		list.push({ label: "Requires", kind: "tags", tags: item.requires ?? [] })
		list.push({ label: "Uses", kind: "tags", tags: item.uses ?? [] })
		list.push({ label: "Keeps its list", kind: "flag", value: item.keepsList === true })
	}
	// how a use of it reads in the playlist editor, with the task's fields in braces (a provider is never a track)
	if(props.kind !== "provider") list.push({ label: "Shown as", kind: "text", value: item.describe ?? "" })
	return list
})
</script>
<style scoped>
.item-info {
	display: grid;
	grid-template-columns: max-content 1fr;
	gap: 0.5rem 1.25rem;
	margin: 0.75rem 0;
	padding: 0.75rem 1rem;
	width: 100%;
	box-sizing: border-box;
	background: var(--p-content-background);
	border: 1px solid var(--p-content-border-color);
	border-radius: var(--p-content-border-radius);
}
.item-info dt {
	font-weight: bold;
	color: var(--p-text-muted-color);
	text-align: right;
}
.item-info dd {
	margin: 0;
	min-width: 0;
	overflow-wrap: anywhere;
}
.item-info .tag {
	margin: 0 0.375rem 0.25rem 0;
}
.item-info .none {
	color: var(--p-text-muted-color);
}
@media (max-width: 40rem) {
	.item-info { grid-template-columns: 1fr; }
	.item-info dt { text-align: left; }
}
</style>
