<template>
	<div class="color-field">
		<ColorPicker format="hex" :modelValue="pickerValue" :inputId="inputId ? `${inputId}-picker` : undefined" :aria-label="`${label} picker`"
			@update:modelValue="(v: unknown) => typeof v === 'string' && emit(`#${v.toLowerCase()}`)" />
		<InputText size="small" fluid :id="inputId" :modelValue="modelValue ?? ''" :placeholder="placeholder ?? '#3366cc'" :aria-label="label" :invalid="invalid"
			@update:modelValue="(v: string|undefined) => emit(v === '' || v === undefined ? null : v)" />
	</div>
</template>
<script setup lang="ts">
/** A `format: "color"` field: a `#rrggbb` (or `#rgb`) value, picked or typed. */
import { computed } from "vue"
import { ColorPicker, InputText } from "primevue"

const props = defineProps<{ modelValue?: string|null, label: string, inputId?: string, invalid?: boolean, placeholder?: string }>()
const emits = defineEmits<{ (e: "update:modelValue", value: string|null): void }>()
const emit = (value: string|null) => emits("update:modelValue", value)

// the picker reads six digits and no `#`; a value it cannot read leaves it at its own default
const pickerValue = computed(() => {
	const v = props.modelValue ?? ""
	if (/^#[0-9a-fA-F]{6}$/.test(v)) return v.slice(1)
	if (/^#[0-9a-fA-F]{3}$/.test(v)) return [...v.slice(1)].map(c => c + c).join("")
	return undefined
})
</script>
<style scoped>
.color-field {
	display: flex;
	gap: .25rem;
	align-items: center;
	width: 100%;
}
</style>
