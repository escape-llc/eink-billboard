<template>
	<div class="array-field" role="group" :aria-label="field.title">
		<div v-if="rows.length > 0" class="array-row array-head">
			<div v-for="f in itemFields" :key="f.name" class="array-cell">{{ f.title }}</div>
			<div class="array-buttons"></div>
		</div>
		<div v-for="(row, index) in rows" :key="index" class="array-row">
			<div v-for="f in itemFields" :key="f.name" class="array-cell">
				<ToggleSwitch v-if="f.type === 'boolean'" size="small" :modelValue="row[f.name] === true" :aria-label="`${f.title} ${index + 1}`"
					@update:modelValue="(v: boolean) => change(index, f.name, v)" />
				<Select v-else-if="f.enum" size="small" fluid :options="f.enum" :modelValue="row[f.name]" :placeholder="f.title" :aria-label="`${f.title} ${index + 1}`"
					:showClear="f.required !== true" :invalid="!!cellError(index, f.name)"
					@update:modelValue="(v: unknown) => change(index, f.name, v ?? null)" />
				<InputNumber v-else-if="f.type === 'number' || f.type === 'integer'" size="small" fluid :modelValue="numeric(row, f.name)" :aria-label="`${f.title} ${index + 1}`"
					:min="f.minimum" :max="f.maximum" :step="f.step" :invalid="!!cellError(index, f.name)"
					:minFractionDigits="f.type === 'integer' ? 0 : f.minFractionDigits" :maxFractionDigits="f.type === 'integer' ? 0 : f.maxFractionDigits"
					@update:modelValue="(v: number|null) => change(index, f.name, v)" />
				<InputText v-else size="small" fluid :modelValue="text(row, f.name)" :placeholder="f.title" :aria-label="`${f.title} ${index + 1}`"
					:invalid="!!cellError(index, f.name)"
					@update:modelValue="(v: string|undefined) => change(index, f.name, v === '' || v === undefined ? null : v)" />
				<Message v-if="cellError(index, f.name)" severity="error" size="small" variant="simple">{{ cellError(index, f.name) }}</Message>
			</div>
			<div class="array-buttons">
				<Button icon="pi pi-arrow-up" size="small" class="p-button-text" :aria-label="`Move ${index + 1} up`" :disabled="index === 0" @click="move(index, -1)" />
				<Button icon="pi pi-arrow-down" size="small" class="p-button-text" :aria-label="`Move ${index + 1} down`" :disabled="index === rows.length - 1" @click="move(index, 1)" />
				<Button icon="pi pi-trash" size="small" severity="danger" class="p-button-text" :aria-label="`Remove ${index + 1}`" @click="remove(index)" />
			</div>
		</div>
		<Message v-if="rowErrors(undefined).length" severity="error" size="small" variant="simple">{{ rowErrors(undefined)[0]!.message }}</Message>
		<div>
			<Button icon="pi pi-plus" size="small" severity="secondary" label="Add" :aria-label="`Add to ${field.title}`"
				:disabled="field.maxItems !== undefined && rows.length >= field.maxItems" @click="add" />
		</div>
	</div>
</template>
<script setup lang="ts">
import { computed } from "vue"
import { Button, InputNumber, InputText, Message, Select, ToggleSwitch } from "primevue"

type Row = Record<string, unknown>
export interface PropsType {
	/** the array property (`items.properties` are the fields of a row) */
	field: any
	modelValue?: Row[] | null
	/** the form's errors of this field: `path` (after the field's name) names the row and field of a problem; none means the list as a whole */
	errors?: { message?: string, path?: string[] }[]
}
const props = defineProps<PropsType>()
const emits = defineEmits<{ (e: "update:modelValue", value: Row[]): void }>()

const itemFields = computed<any[]>(() => props.field.items?.properties ?? [])
const rows = computed<Row[]>(() => Array.isArray(props.modelValue) ? props.modelValue : [])

const text = (row: Row, name: string): string => typeof row[name] === "string" ? row[name] : ""
const numeric = (row: Row, name: string): number|null => typeof row[name] === "number" ? row[name] : null
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
.array-buttons {
	display: flex;
	flex: 0 0 auto;
	min-width: 7.5rem;
}
</style>
