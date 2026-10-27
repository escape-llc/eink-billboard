<template>
	<div class="array-field" :class="{ stacked }" role="group" :aria-label="field.title">
		<template v-for="(row, index) in rows" :key="index">
		<div class="array-row">
			<div v-for="f in itemFields" :key="f.name" class="array-cell" :class="{ hidden: !isVisible(f, row) }">
				<template v-if="isVisible(f, row)">
					<!-- a location is chosen on a map, as everywhere else (the System settings): the picker sits in the row, a block of its own, under its title -->
					<template v-if="f.type === 'location'">
						<label class="array-label">{{ f.title }}</label>
						<div class="array-location" :class="{ invalid: !!cellError(index, f.name) }">
							<LeafletPicker :name="`${f.name}-${index}`" :modelValue="(row[f.name] as { latitude: number, longitude: number } | null) ?? undefined" @change="(e: { value: unknown }) => change(index, f.name, e.value)" />
						</div>
					</template>
					<!-- every other cell is a group of fluid controls, as the settings form's fields are; the title is the control's own label -->
					<InputGroup v-else class="array-group">
						<template v-if="f.type === 'boolean'">
							<InputGroupAddon><ToggleSwitch size="small" :inputId="idOf(index, f.name)" :modelValue="row[f.name] === true" :aria-label="`${f.title} ${index + 1}`"
								@update:modelValue="(v: boolean) => change(index, f.name, v)" /></InputGroupAddon>
							<InputGroupAddon class="array-toggle-label"><label :for="idOf(index, f.name)">{{ f.title }}</label></InputGroupAddon>
						</template>
						<IftaLabel v-else-if="f.enum">
							<Select size="small" fluid :inputId="idOf(index, f.name)" :options="f.enum" :modelValue="row[f.name]" :aria-label="`${f.title} ${index + 1}`"
								:showClear="f.required !== true" :invalid="!!cellError(index, f.name)"
								@update:modelValue="(v: unknown) => change(index, f.name, v ?? null)" />
							<label :for="idOf(index, f.name)">{{ f.title }}</label>
						</IftaLabel>
						<IftaLabel v-else-if="f.lookup">
							<Select size="small" fluid :inputId="idOf(index, f.name)" :options="choices(f, row)" optionLabel="name" optionValue="value" :modelValue="row[f.name]"
								:placeholder="placeholder(f, row)" :aria-label="`${f.title} ${index + 1}`" :showClear="f.required !== true" :invalid="!!cellError(index, f.name)"
								@update:modelValue="(v: unknown) => change(index, f.name, v ?? null)" />
							<label :for="idOf(index, f.name)">{{ f.title }}</label>
						</IftaLabel>
						<IftaLabel v-else-if="f.type === 'number' || f.type === 'integer'">
							<InputNumber size="small" fluid :inputId="idOf(index, f.name)" :modelValue="numeric(row, f.name)" :aria-label="`${f.title} ${index + 1}`"
								:min="f.minimum" :max="f.maximum" :step="f.step" :invalid="!!cellError(index, f.name)"
								:minFractionDigits="f.type === 'integer' ? 0 : f.minFractionDigits" :maxFractionDigits="f.type === 'integer' ? 0 : f.maxFractionDigits"
								@update:modelValue="(v: number|null) => change(index, f.name, v)" />
							<label :for="idOf(index, f.name)">{{ f.title }}</label>
						</IftaLabel>
						<ColorField v-else-if="f.format === 'color'" grouped :title="f.title" :inputId="idOf(index, f.name)" :modelValue="text(row, f.name) || null" :label="`${f.title} ${index + 1}`"
							:invalid="!!cellError(index, f.name)" @update:modelValue="(v: string|null) => change(index, f.name, v)" />
						<IftaLabel v-else>
							<InputText size="small" fluid :id="idOf(index, f.name)" :modelValue="text(row, f.name)" :aria-label="`${f.title} ${index + 1}`"
								:type="f.writeOnly ? 'password' : f.format === 'uri' ? 'url' : 'text'" :autocomplete="f.writeOnly ? 'new-password' : undefined"
								:invalid="!!cellError(index, f.name)"
								@update:modelValue="(v: string|undefined) => change(index, f.name, v === '' || v === undefined ? null : v)" />
							<label :for="idOf(index, f.name)">{{ f.title }}</label>
						</IftaLabel>
						<TestUrlButton v-if="f.test?.url && baseUrl !== undefined" bare :route="f.test.url" :baseUrl="baseUrl" :value="row[f.name]" :label="`${f.title} ${index + 1}`"
							:disabled="!!cellError(index, f.name)" @result="(r: TestResult | null) => tested[`${index}:${f.name}`] = r" />
					</InputGroup>
					<Message v-if="f.lookup && rowLookup(f, row)?.error" severity="warn" size="small" variant="simple">{{ rowLookup(f, row)?.error }}</Message>
					<Message v-if="cellError(index, f.name)" severity="error" size="small" variant="simple">{{ cellError(index, f.name) }}</Message>
					<Message v-if="tested[`${index}:${f.name}`]" :severity="tested[`${index}:${f.name}`]!.ok ? 'success' : 'error'" size="small" variant="simple">{{ tested[`${index}:${f.name}`]!.message }}</Message>
				</template>
			</div>
			<RowAction v-if="rowItems?.action && baseUrl !== undefined" class="array-action" :action="rowItems.action" :baseUrl="baseUrl"
				:rowKey="rowItems.key ? row[rowItems.key] : undefined" :label="`${field.title} ${index + 1}`" />
			<InputGroup class="array-buttons">
				<Button icon="mi mi-arrow-upward" size="small" title="Move up" :aria-label="`Move ${index + 1} up`" :disabled="index === 0" @click="move(index, -1)" />
				<Button icon="mi mi-arrow-downward" size="small" title="Move down" :aria-label="`Move ${index + 1} down`" :disabled="index === rows.length - 1" @click="move(index, 1)" />
				<Button icon="mi mi-delete" size="small" severity="danger" title="Remove" :aria-label="`Remove ${index + 1}`" @click="remove(index)" />
			</InputGroup>
		</div>
		<!-- a row that carries a plugin's settings (items.plugin): they are set in the plugin's own form, in a dialog -->
		<div v-if="carries(row)" class="array-plugin">
			<Button size="small" icon="mi mi-settings" type="button" :title="hasContent(row) ? 'Task settings' : 'Set up the task'" :aria-label="`Task settings ${index + 1}`" @click="editing = index" />
			<Button v-if="rowPlugin?.run && baseUrl !== undefined" size="small" icon="mi mi-play-arrow" type="button" title="Run now" :aria-label="`Run task ${index + 1} now`"
				:loading="running === index" :disabled="running === index || !hasContent(row) || row[rowItems?.key ?? ''] === undefined || row[rowItems?.key ?? ''] === null" @click="runRow(index, row)" />
			<Message v-if="ranIndex === index && ran" :severity="ran.ok ? 'success' : 'error'" size="small" variant="simple">{{ ran.message }}</Message>
			<Message v-if="rowPlugin && cellError(index, rowPlugin.field)" severity="error" size="small" variant="simple">{{ cellError(index, rowPlugin.field) }}</Message>
		</div>
		</template>
		<RowPluginDialog v-if="rowPlugin && editing !== null && baseUrl !== undefined" :pluginId="rowPlugin.id" :title="`Task for ${field.title} ${editing + 1}`" :content="(rows[editing]?.[rowPlugin.field] as FormValues | null | undefined) ?? null"
			:baseUrl="baseUrl" @apply="applyPlugin" @close="editing = null" />
		<Message v-if="rowErrors(undefined).length" severity="error" size="small" variant="simple">{{ rowErrors(undefined)[0]!.message }}</Message>
		<div>
			<Button icon="mi mi-add" size="small" title="Add" :aria-label="`Add to ${field.title}`"
				:disabled="field.maxItems !== undefined && rows.length >= field.maxItems" @click="add" />
		</div>
	</div>
</template>
<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, reactive, ref, watch } from "vue"
import { useQueryCache } from "@pinia/colada"
import { readResource } from "../api/resources"
import { lookupAddress, withStored } from "./LookupQuery"
import { Button, IftaLabel, InputGroup, InputGroupAddon, InputNumber, InputText, Message, Select, ToggleSwitch } from "primevue"
import ColorField from "./ColorField.vue"
import { apiPost, joinUrl } from "./ApiClient"
// a dialog that is a whole form of its own, which holds list fields: loaded when it is first opened, so the two do not import each other
const RowPluginDialog = defineAsyncComponent(() => import("./RowPluginDialog.vue"))
import LeafletPicker from "./LeafletPicker.vue"
import RowAction from "./RowAction.vue"
import TestUrlButton, { type TestResult } from "./TestUrlButton.vue"
import { isVisible } from "./FormVisibility"
import type { FormValues, ResolvedFieldDef } from "./FormDefs"

type Row = Record<string, unknown>
type Choice = { name: string, value: unknown }
export interface PropsType {
	/** the array property (`items.properties` are the fields of a row; a field with a `lookup` carries its resolved `list`) */
	field: ResolvedFieldDef
	/** where the API is, for a field's Test button */
	baseUrl?: string
	modelValue?: Row[] | null
	/** the form's errors of this field: `path` (after the field's name) names the row and field of a problem; none means the list as a whole */
	errors?: { message?: string, path?: string[] }[]
}
const props = defineProps<PropsType>()
const emits = defineEmits<{ (e: "update:modelValue", value: Row[]): void }>()

/** a list of objects' item definition: its row fields, key and row action */
const rowItems = computed(() => props.field.items?.type === "object" ? props.field.items : undefined)
const itemFields = computed<ResolvedFieldDef[]>(() => rowItems.value?.properties ?? [])
/** the answer of each Test button of the rows (`row:field`), shown under its cell */
const tested = reactive<Record<string, TestResult | null>>({})
/** the id of a row's control, for the label that names it */
const uid = Math.random().toString(36).slice(2, 8)
const idOf = (index: number, name: string) => `${props.field.name}-${name}-${index}-${uid}`
const rows = computed<Row[]>(() => Array.isArray(props.modelValue) ? props.modelValue : [])
// more fields than fit across: each row is a block of fields that wrap, instead of one line
// (a map needs room: a row with a location is a block too)
const stacked = computed(() => itemFields.value.length > 4 || itemFields.value.some(f => f.type === "location"))

// the settings a row carries for a plugin (`items.plugin`), set in a dialog of the plugin's own form
const rowPlugin = computed(() => rowItems.value?.plugin)
const carries = (row: Row) => rowPlugin.value !== undefined && row[rowPlugin.value.when.field] === rowPlugin.value.when.const
const hasContent = (row: Row) => rowPlugin.value !== undefined && typeof row[rowPlugin.value.field] === "object" && row[rowPlugin.value.field] !== null
const editing = ref<number | null>(null)
function applyPlugin(values: FormValues) {
	if (editing.value !== null && rowPlugin.value) change(editing.value, rowPlugin.value.field, values)
	editing.value = null
}
const running = ref<number | null>(null)
const ranIndex = ref<number | null>(null)
const ran = ref<{ ok: boolean, message: string } | null>(null)
/** Run the saved row now (`items.plugin.run`: the address of the list, then the row's key): what was saved runs, not what is typed. */
async function runRow(index: number, row: Row) {
	if (!rowPlugin.value?.run || !rowItems.value?.key || props.baseUrl === undefined) return
	running.value = index
	ranIndex.value = index
	try {
		await apiPost(joinUrl(props.baseUrl, `${rowPlugin.value.run}/${row[rowItems.value.key]}/run`), undefined)
		ran.value = { ok: true, message: "Started." }
	}
	catch (ex: unknown) {
		ran.value = { ok: false, message: (ex instanceof Error && ex.message) || "The task could not be started." }
	}
	finally {
		running.value = null
	}
}

const text = (row: Row, name: string): string => typeof row[name] === "string" ? row[name] : ""
const numeric = (row: Row, name: string): number|null => typeof row[name] === "number" ? row[name] : null
// a row field's lookup sent with the row's own fields (`with`, #510 A8): a list per row, kept by its address, so rows that send the same values share it
const rowLists = reactive(new Map<string, { list: Choice[], error?: string }>())
/** Where a row's lookup is asked (or which of the row's fields it waits for); null: a lookup without `with`, whose one list is the field's. */
function rowAddress(f: ResolvedFieldDef, row: Row) {
	return f.lookupWith?.length && f.lookupUrl ? lookupAddress(f.lookupUrl, f.lookupWith, name => row[name]) : null
}
function rowLookup(f: ResolvedFieldDef, row: Row) {
	const wanted = rowAddress(f, row)
	return wanted?.address !== undefined ? rowLists.get(wanted.address) : undefined
}
/** A lookup's choices, with the row's value kept when the list does not offer it (renamed, deleted, or not loaded): it must not look unset. */
function choices(f: ResolvedFieldDef, row: Row): Choice[] {
	const wanted = rowAddress(f, row)
	const list: Choice[] = wanted ? (rowLookup(f, row)?.list ?? []) : Array.isArray(f.list) ? f.list : []
	return withStored(list, row[f.name])
}
/** A row's lookup that waits for a field of the row says which; any other shows its title. */
function placeholder(f: ResolvedFieldDef, row: Row): string {
	const missing = rowAddress(f, row)?.missing
	return missing ? `Choose ${itemFields.value.find(x => x.name === missing)?.title ?? missing} first` : f.title
}
// the addresses the rows need now: each is asked once, after the rows have been still a moment (a typed value changes per keystroke)
const wantedAddresses = computed(() => {
	const all = new Set<string>()
	for (const row of rows.value) for (const f of itemFields.value) {
		const address = rowAddress(f, row)?.address
		if (address !== undefined) all.add(address)
	}
	return [...all].sort()
})
let rowTimer: ReturnType<typeof setTimeout> | undefined
// a row's choices are read through the cache: rows that ask the same question (and other forms) share one answer
const queryCache = useQueryCache()
watch(wantedAddresses, (addresses, before) => {
	clearTimeout(rowTimer)
	rowTimer = setTimeout(() => {
		for (const address of addresses) {
			if (rowLists.has(address)) continue
			rowLists.set(address, { list: [] })
			readResource<Choice[]>(queryCache, address)
				.then(list => rowLists.set(address, { list }))
				.catch(ex => {
					console.error("lookup", ex)
					// the message is shown under the cell; it is never a choice that could be saved
					rowLists.set(address, { list: [], error: `The choices could not be loaded: ${ex.message}` })
				})
		}
	}, before === undefined ? 0 : 300)
}, { immediate: true })
onBeforeUnmount(() => clearTimeout(rowTimer))
function emptyRow(): Row {
	const row: Row = {}
	for (const f of itemFields.value) {
		row[f.name] = f.default ?? (f.type === "boolean" ? false : null)
	}
	return row
}
function emit(next: Row[]) {
	emits("update:modelValue", next)
}
const change = (index: number, name: string, value: unknown) => emit(rows.value.map((r, i) => i === index ? { ...r, [name]: value } : r))
const add = () => emit([...rows.value, emptyRow()])
const remove = (index: number) => emit(rows.value.filter((_, i) => i !== index))
function move(index: number, by: number) {
	const next = [...rows.value]
	const target = index + by
	if (target < 0 || target >= next.length) return
	;[next[index], next[target]] = [next[target]!, next[index]!]
	emit(next)
}
/** The problems of one row (`index`), or of the list as a whole (`undefined`). */
function rowErrors(index: number|undefined) {
	return (props.errors ?? []).filter(e => index === undefined ? !e.path?.length : e.path?.[0] === String(index))
}
function cellError(index: number, name: string): string|undefined {
	return rowErrors(index).find(e => e.path?.[1] === name)?.message
}
</script>
<style scoped>
.array-location {
	width: 100%;
	height: 300px;
}
.array-location.invalid {
	outline: 1px solid var(--p-red-500);
}
.array-field {
	display: flex;
	flex-direction: column;
	gap: .25rem;
	width: 100%;
	padding: .25rem;
}
.array-row {
	display: flex;
	gap: .25rem;
	align-items: flex-start;
}
.array-plugin {
	display: flex;
	flex-wrap: wrap;
	align-items: center;
	gap: .25rem;
	margin: 0 0 .5rem .25rem;
}
.array-cell {
	flex: 1 1 0;
	min-width: 0;
}
/* a cell is a group of fluid controls: the labelled control takes what the addons leave. The editor itself may sit inside an InputGroup, whose rule
	(.p-inputgroup .p-inputtext: width 1%) outweighs the controls' own `fluid`, so the controls say their width again */
.array-group > :deep(.p-iftalabel) {
	flex: 1 1 0;
	min-width: 0;
}
.array-group :deep(.p-inputtext),
.array-group :deep(.p-select),
.array-group :deep(.p-inputnumber) {
	width: 100%;
}
.array-toggle-label {
	flex: 1 1 auto;
	justify-content: flex-start;
	font-size: .875rem;
}
.array-buttons {
	flex: 0 0 auto;
	width: auto;
}
.stacked .array-row {
	flex-wrap: wrap;
	gap: .5rem;
	padding: .5rem;
	border: 1px solid var(--p-content-border-color);
	border-radius: var(--p-content-border-radius);
}
.stacked .array-cell {
	flex: 1 1 12rem;
}
.stacked .array-cell.hidden {
	display: none;
}
.array-action {
	flex-basis: 100%;
}
.array-row:has(.array-action) {
	flex-wrap: wrap;
}
.stacked .array-buttons {
	flex-basis: 100%;
	justify-content: flex-end;
}
.array-label {
	display: block;
	font-size: 85%;
	font-weight: bold;
	margin-bottom: .125rem;
}
</style>
