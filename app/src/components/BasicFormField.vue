<template>
	<InputGroup>
		<InputGroupAddon>
			<slot name="label" v-bind="{ field, fieldState }">
				<label :style="{'width': props.fieldNameWidth, 'max-width': props.fieldNameWidth }"
					style="flex-shrink:0;flex-grow:1" :for="field.name">{{ field.label }}</label>
			</slot>
		</InputGroupAddon>
		<template v-if="field.type === 'boolean'">
			<InputGroupAddon style="flex-grow:1">
				<ToggleSwitch :name="field.name" size="small" fluid />
			</InputGroupAddon>
		</template>
		<template v-if="field.type === 'schema'">
			<Select size="small" :name="field.name" :options="field.list"
				optionLabel="name" optionValue="value" :showClear="field.required === false"
				:placeholder="field.label" fluid @change="handleSchemaChange($event, field)" />
		</template>
		<template v-else-if="'enum' in field">
			<Select size="small" :name="field.name" :options="field.enum"
				:showClear="field.required === false"
				:placeholder="field.label" fluid />
		</template>
		<template v-else-if="'lookup' in field">
			<Select size="small" :name="field.name" :options="field.list"
				optionLabel="name" optionValue="value" :showClear="field.required === false"
				:placeholder="field.label" fluid />
		</template>
		<template v-else-if="field.type === 'number'">
			<InputNumber style="flex-grow:1" :name="field.name" size="small"
				:min="field.min" :max="field.max" :step="field.step" :showButtons="true"
				:minFractionDigits="field.minFractionDigits || 0" :maxFractionDigits="field.maxFractionDigits || 0"
				:showClear="field.required === false"
				:placeholder="field.label" fluid />
		</template>
		<template v-else-if="field.type === 'location'">
			<InputGroupAddon style="flex-grow:1">
				<FormField style="width:100%;height:300px" :name="field.name" v-slot="$field" :validateOnValueUpdate="true">
					<LeafletPicker :name="field.name" :modelValue="$field.value" @change="$field.onChange" />
				</FormField>
			</InputGroupAddon>
		</template>
		<template v-else>
			<InputText style="flex-grow:1" :name="field.name" size="small" type="text"
				:placeholder="field.label" fluid />
		</template>
	</InputGroup>
	<slot name="message" v-bind="{ field, fieldState }">
		<Message v-if="isInvalid"
			severity="error" size="small" variant="simple">{{ errorMessage }}</Message>
	</slot>
	<template v-if="field.children?.length">
		<BasicFormField 
			v-for="child in field.children" 
			:key="child.name" 
			:field="child"
			:formContext="formContext"
			:fieldNameWidth="fieldNameWidth"
		>
			<!-- Forward all slots to descendants -->
			<template v-for="(_, name) in $slots" #[name]="slotProps">
				<slot :name="name" v-bind="slotProps || {}" />
			</template>
		</BasicFormField>
	</template>
</template>
<script setup lang="ts">
import { Message, InputGroup, ToggleSwitch, InputGroupAddon, InputText, InputNumber, Select } from 'primevue';
import FormField from '@primevue/forms/formfield';
import LeafletPicker from './LeafletPicker.vue';
import { computed, toRaw } from 'vue';
export interface PropsType {
	field: any
	// pass the v-slot="$form" to this prop
	formContext: any
	fieldNameWidth?: string
}
export interface SchemaChangeData {
	type: 'schema-change'
	field: any
	selected: any
}
export interface EmitsType {
	(e: 'form-field-event', data: SchemaChangeData): void
}

const props = defineProps<PropsType>()
const emits = defineEmits<EmitsType>()
function handleSchemaChange(event: any, field: any) {
	console.log("Schema change", event, field)
	// emit an event to the parent with the selected schema
	const schema = field.list.find((s: any) => s.value === event.value);
	if (schema) {
		// populate field.children with the properties of the selected schema
//		props.formContext.onChange(field.name, event.value);
		emits('form-field-event', { type: 'schema-change', field, selected: toRaw(schema) });
	}
}
const fieldState = computed(() => props.formContext?.[props.field.name] || {});
const isInvalid = computed(() => !!fieldState.value.invalid);
const errorMessage = computed(() => fieldState.value.error?.message);
</script>
<style scoped>
</style>