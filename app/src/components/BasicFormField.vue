<template>
	<template v-if="field.type === 'header'">
		<slot name="group-header" v-bind="field">
			<div>{{ field.title }}</div>
		</slot>
	</template>
	<template v-else-if="visible">
		<InputGroup>
			<InputGroupAddon>
				<slot name="label" v-bind="{ field, fieldState }">
					<label :style="{'width': props.fieldNameWidth, 'max-width': props.fieldNameWidth }"
						style="flex-shrink:0;flex-grow:1" :for="field.name">{{ field.title }}</label>
				</slot>
			</InputGroupAddon>
			<template v-if="field.type === 'boolean'">
				<InputGroupAddon style="flex-grow:1;justify-content:flex-start">
					<ToggleSwitch :name="field.name" :inputId="field.name" size="small" fluid />
				</InputGroupAddon>
			</template>
			<template v-else-if="field.type === 'schema'">
				<Select size="small" :name="field.name" :inputId="field.name" :invalid="isInvalid" :options="field.list"
					optionLabel="name" optionValue="value" :showClear="field.required === false"
					:placeholder="field.title" fluid @change="handleSchemaChange($event, field)" />
			</template>
			<template v-else-if="field.type === 'string' && field.format === 'date'">
				<InputGroupAddon style="flex-grow:1">
					<FormField style="width:100%" :name="field.name" v-slot="$field" :validateOnValueUpdate="true">
						<DatePicker size="small" fluid showIcon showButtonBar dateFormat="yy-mm-dd" :inputId="field.name" :invalid="isInvalid"
							:modelValue="isoToDate($field.value)" :placeholder="field.title"
							@update:modelValue="(d: Date|(Date|null)[]|null|undefined) => $field.props.onChange(dateToIso(Array.isArray(d) ? d[0] : d))" />
					</FormField>
				</InputGroupAddon>
			</template>
			<template v-else-if="'enum' in field">
				<Select size="small" :name="field.name" :inputId="field.name" :invalid="isInvalid" :options="field.enum"
					:showClear="field.required === false"
					:placeholder="field.title" fluid />
			</template>
			<template v-else-if="'lookup' in field">
				<Select size="small" :name="field.name" :inputId="field.name" :invalid="isInvalid" :options="field.list"
					optionLabel="name" optionValue="value" :showClear="field.required === false"
					:placeholder="field.title" fluid />
			</template>
			<template v-else-if="field.type === 'number' || field.type === 'integer'">
				<InputNumber style="flex-grow:1" :name="field.name" :inputId="field.name" :invalid="isInvalid" size="small"
					:min="field.minimum" :max="field.maximum" :step="field.step" :showButtons="true"
					:minFractionDigits="field.type === 'integer' ? 0 : field.minFractionDigits"
					:maxFractionDigits="field.type === 'integer' ? 0 : field.maxFractionDigits"
					:showClear="field.required === false"
					:placeholder="field.title" fluid />
			</template>
			<template v-else-if="field.type === 'location'">
				<InputGroupAddon style="flex-grow:1">
					<FormField style="width:100%;height:300px" :name="field.name" v-slot="$field" :validateOnValueUpdate="true">
						<LeafletPicker :name="field.name" :modelValue="$field.value" @change="$field.props.onChange" />
					</FormField>
				</InputGroupAddon>
			</template>
			<template v-else>
				<InputText style="flex-grow:1" :name="field.name" :id="field.name" :invalid="isInvalid" size="small" :type="field.writeOnly ? 'password' : 'text'"
					:autocomplete="field.writeOnly ? 'new-password' : undefined"
					:placeholder="field.title" fluid />
			</template>
		</InputGroup>
		<slot name="message" v-bind="{ field, fieldState }">
			<Message v-if="isInvalid"
				severity="error" size="small" variant="simple">{{ errorMessage }}</Message>
		</slot>
		<Message v-if="field.lookupError" severity="warn" size="small" variant="simple">{{ field.lookupError }}</Message>
		<Message v-if="field.description" severity="secondary" size="small" variant="simple">{{ field.description }}</Message>
		<template v-if="field.children?.length">
			<BasicFormField 
				v-for="child in field.children" 
				:key="child.name" 
				:field="child"
				:formContext="formContext"
				:fieldNameWidth="fieldNameWidth"
				@form-field-event="(data: SchemaChangeData) => emits('form-field-event', data)"
			>
				<!-- Forward all slots to descendants -->
				<template v-for="(_, name) in $slots" #[name]="slotProps">
					<slot :name="name" v-bind="slotProps || {}" />
				</template>
			</BasicFormField>
		</template>
	</template>
</template>
<script setup lang="ts">
import { Message, InputGroup, ToggleSwitch, InputGroupAddon, InputText, InputNumber, Select, DatePicker } from 'primevue';
import FormField from '@primevue/forms/formfield';
import LeafletPicker from './LeafletPicker.vue';
import { isoToDate, dateToIso } from './FormDates';
import { isVisible } from './FormVisibility';
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
// explicit slot types: the template forwards every slot to the recursive child, which TypeScript cannot infer
defineSlots<Record<string, (props: any) => any>>()
const emits = defineEmits<EmitsType>()
function handleSchemaChange(event: any, field: any) {
	// emit an event to the parent with the selected schema
	// a cleared choice (no match) still tells the parent, which drops the previous choice's fields
	const schema = field.list.find((s: any) => s.value === event.value);
	emits('form-field-event', { type: 'schema-change', field, selected: schema ? toRaw(schema) : null });
}
const fieldState = computed(() => props.formContext?.[props.field.name] || {});
// the form's field states, read by name, are the values the predicates look at
const visible = computed(() => isVisible(props.field, (name: string) => props.formContext?.[name]?.value))
const isInvalid = computed(() => !!fieldState.value.invalid);
const errorMessage = computed(() => fieldState.value.error?.message);
</script>
<style scoped>
</style>