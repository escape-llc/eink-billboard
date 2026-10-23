<template>
	<div class="array-field" :class="{ stacked }" role="group" :aria-label="field.title">
		<div v-if="rows.length > 0 && !stacked" class="array-row array-head">
			<div v-for="f in itemFields" :key="f.name" class="array-cell">{{ f.title }}</div>
			<div class="array-buttons"></div>
		</div>
		<div v-for="(row, index) in rows" :key="index" class="array-row">
			<div v-for="f in itemFields" :key="f.name" class="array-cell" :class="{ hidden: !isVisible(f, row) }">
				<template v-if="isVisible(f, row)">
					<label v-if="stacked" class="array-label">{{ f.title }}</label>
					<ToggleSwitch v-if="f.type === 'boolean'" size="small" :modelValue="row[f.name] === true" :aria-label="`${f.title} ${index + 1}`"
						@update:modelValue="(v: boolean) => change(index, f.name, v)" />
					<!-- a location is chosen on a map, as everywhere else (the System settings): the picker sits in the row, a block of its own -->
					<div v-else-if="f.type === 'location'" class="array-location" :class="{ invalid: !!cellError(index, f.name) }">
						<LeafletPicker :name="`${f.name}-${index}`" :modelValue="(row[f.name] as { latitude: number, longitude: number } | null) ?? undefined" @change="(e: { value: unknown }) => change(index, f.name, e.value)" />
					</div>
					<Select v-else-if="f.enum" size="small" fluid :options="f.enum" :modelValue="row[f.name]" :placeholder="f.title" :aria-label="`${f.title} ${index + 1}`"
						:showClear="f.required !== true" :invalid="!!cellError(index, f.name)"
						@update:modelValue="(v: unknown) => change(index, f.name, v ?? null)" />
					<Select v-else-if="f.lookup" size="small" fluid :options="choices(f, row)" optionLabel="name" optionValue="value" :modelValue="row[f.name]"
						:placeholder="f.title" :aria-label="`${f.title} ${index + 1}`" :showClear="f.required !== true" :invalid="!!cellError(index, f.name)"
						@update:modelValue="(v: unknown) => change(index, f.name, v ?? null)" />
					<InputNumber v-else-if="f.type === 'number' || f.type === 'integer'" size="small" fluid :modelValue="numeric(row, f.name)" :aria-label="`${f.title} ${index + 1}`"
						:min="f.minimum" :max="f.maximum" :step="f.step" :invalid="!!cellError(index, f.name)"
						:minFractionDigits="f.type === 'integer' ? 0 : f.minFractionDigits" :maxFractionDigits="f.type === 'integer' ? 0 : f.maxFractionDigits"
						@update:modelValue="(v: number|null) => change(index, f.name, v)" />
					<ColorField v-else-if="f.format === 'color'" :modelValue="text(row, f.name) || null" :label="`${f.title} ${index + 1}`" :invalid="!!cellError(index, f.name)"
						@update:modelValue="(v: string|null) => change(index, f.name, v)" />
					<InputText v-else size="small" fluid :modelValue="text(row, f.name)" :placeholder="f.title" :aria-label="`${f.title} ${index + 1}`"
						:type="f.writeOnly ? 'password' : f.format === 'uri' ? 'url' : 'text'" :autocomplete="f.writeOnly ? 'new-password' : undefined"
						:invalid="!!cellError(index, f.name)"
						@update:modelValue="(v: string|undefined) => change(index, f.name, v === '' || v === undefined ? null : v)" />
					<Message v-if="cellError(index, f.name)" severity="error" size="small" variant="simple">{{ cellError(index, f.name) }}</Message>
					<TestUrlButton v-if="f.test?.url && baseUrl !== undefined" :route="f.test.url" :baseUrl="baseUrl" :value="row[f.name]" :label="`${f.title} ${index + 1}`"
						:disabled="!!cellError(index, f.name)" />
				</template>
			</div>
			<RowAction v-if="rowItems?.action && baseUrl !== undefined" class="array-action" :action="rowItems.action" :baseUrl="baseUrl"
				:rowKey="rowItems.key ? row[rowItems.key] : undefined" :label="`${field.title} ${index + 1}`" />
			<div class="array-buttons">
				<Button icon="mi mi-arrow-upward" size="small" class="p-button-text" :aria-label="`Move ${index + 1} up`" :disabled="index === 0" @click="move(index, -1)" />
				<Button icon="mi mi-arrow-downward" size="small" class="p-button-text" :aria-label="`Move ${index + 1} down`" :disabled="index === rows.length - 1" @click="move(index, 1)" />
				<Button icon="mi mi-delete" size="small" severity="danger" class="p-button-text" :aria-label="`Remove ${index + 1}`" @click="remove(index)" />
			</div>
		</div>
		<Message v-if="rowErrors(undefined).length" severity="error" size="small" variant="simple">{{ rowErrors(undefined)[0]!.message }}</Message>
		<div>
			<Button icon="mi mi-add" size="small" severity="secondary" label="Add" :aria-label="`Add to ${field.title}`"
				:disabled="field.maxItems !== undefined && rows.length >= field.maxItems" @click="add" />
		</div>
	</div>
</template>
<script setup lang="ts">
import { computed } from "vue"
import { Button, InputNumber, InputText, Message, Select, ToggleSwitch } from "primevue"
import ColorField from "./ColorField.vue"
import LeafletPicker from "./LeafletPicker.vue"
import RowAction from "./RowAction.vue"
import TestUrlButton from "./TestUrlButton.vue"
import { isVisible } from "./FormVisibility"
import type { ResolvedFieldDef } from "./FormDefs"

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
const rows = computed<Row[]>(() => Array.isArray(props.modelValue) ? props.modelValue : [])
// more fields than fit across: each row is a block of labelled fields instead of a line under one header
// (a map needs room: a row with a location is a block too)
const stacked = computed(() => itemFields.value.length > 4 || itemFields.value.some(f => f.type === "location"))

const text = (row: Row, name: string): string => typeof row[name] === "string" ? row[name] : ""
const numeric = (row: Row, name: string): number|null => typeof row[name] === "number" ? row[name] : null
/** A lookup's choices, with the row's value kept when the list does not offer it (renamed, deleted, or not loaded): it must not look unset. */
function choices(f: ResolvedFieldDef, row: Row): Choice[] {
	const list: Choice[] = Array.isArray(f.list) ? f.list : []
	const current = row[f.name]
	if (current === undefined || current === null || current === "" || list.some(c => c.value === current)) return list
	return [...list, { name: String(current), value: current }]
}
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
.array-head {
	font-weight: bold;
	font-size: 90%;
}
.array-cell {
	flex: 1 1 0;
	min-width: 0;
}
/* the editor sits inside an InputGroup, whose rule (.p-inputgroup .p-inputtext: width 1%) outweighs the controls' own `fluid`: a row's controls fill their cell */
.array-cell > :deep(.p-inputtext),
.array-cell > :deep(.p-select),
.array-cell > :deep(.p-inputnumber) {
	width: 100%;
}
.array-buttons {
	display: flex;
	flex: 0 0 auto;
	min-width: 7.5rem;
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
