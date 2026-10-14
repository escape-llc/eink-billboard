<template>
	<template v-if="field.type === 'header'">
		<slot name="group-header" v-bind="field">
			<div>{{ field.title }}</div>
		</slot>
	</template>
	<template v-else-if="visible">
		<InputGroup>
			<InputGroupAddon class="field-label" :class="{ 'label-top': tall }">
				<slot name="label" v-bind="{ field, fieldState }">
					<label :style="{'width': props.fieldNameWidth, 'max-width': props.fieldNameWidth }"
						style="flex-shrink:0;flex-grow:1" :for="field.name">{{ field.title }}<Tag v-if="isNew" class="new-tag" size="small" severity="info" value="new" title="Not in this item yet: it starts at its default" /></label>
				</slot>
			</InputGroupAddon>
			<template v-if="field.type === 'boolean'">
				<InputGroupAddon style="flex-grow:1;justify-content:flex-start">
					<ToggleSwitch :name="field.name" :inputId="field.name" size="small" fluid />
				</InputGroupAddon>
			</template>
			<template v-else-if="field.type === 'array' && field.items?.type === 'string'">
				<!-- a multi-select: the values chosen from `items.enum` or from the field's lookup -->
				<MultiSelect size="small" :name="field.name" :inputId="field.name" :invalid="isInvalid" :options="choices"
					optionLabel="name" optionValue="value" display="chip" :showClear="field.required !== true"
					:placeholder="field.title" fluid />
			</template>
			<template v-else-if="field.type === 'array'">
				<InputGroupAddon style="flex:1 1 0;min-width:0;padding:0">
					<!-- Registers the field with the form and nothing more: the PrimeVue inputs of the rows would each take the whole field's value if they were inside it.
						The rows are edited outside it, and the form is told the new list. -->
					<FormField :name="field.name" :validateOnValueUpdate="true" />
					<ArrayField :field="field" :baseUrl="baseUrl" :modelValue="fieldState.value" :errors="fieldState.errors"
						@update:modelValue="(v: Record<string, unknown>[]) => emits('form-field-event', { type: 'set-value', field, value: v })" />
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
			<template v-else-if="field.type === 'string' && field.format === 'color'">
				<InputGroupAddon style="flex-grow:1">
					<FormField style="width:100%" :name="field.name" v-slot="$field" :validateOnValueUpdate="true">
						<ColorField :inputId="field.name" :label="field.title" :invalid="isInvalid" :modelValue="$field.value"
							@update:modelValue="(v: string|null) => $field.props.onChange({ value: v })" />
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
				<InputText style="flex-grow:1" :name="field.name" :id="field.name" :invalid="isInvalid" size="small" :type="field.writeOnly ? 'password' : field.format === 'uri' ? 'url' : 'text'"
					:autocomplete="field.writeOnly ? 'new-password' : undefined"
					:placeholder="field.title" fluid />
			</template>
		</InputGroup>
		<TestUrlButton v-if="field.test?.url && field.type === 'string'" :route="field.test.url" :baseUrl="baseUrl ?? ''" :value="fieldState.value"
			:label="field.title" :disabled="isInvalid" />
		<slot name="message" v-bind="{ field, fieldState }">
			<Message v-if="isInvalid && errorMessage"
				severity="error" size="small" variant="simple">{{ errorMessage }}</Message>
		</slot>
		<Message v-if="field.lookupError" severity="warn" size="small" variant="simple">{{ field.lookupError }}</Message>
		<Message v-if="showHelp && field.description" severity="secondary" size="small" variant="simple" class="field-help">{{ field.description }}</Message>
		<div v-if="safeLink">
			<Button as="a" :href="safeLink.url" target="_blank" rel="noopener noreferrer" :label="safeLink.label" icon="pi pi-external-link" size="small" variant="text" />
		</div>
		<template v-if="field.children?.length">
			<BasicFormField 
				v-for="child in field.children" 
				:key="child.name" 
				:field="child"
				:formContext="formContext"
				:fieldNameWidth="fieldNameWidth"
				:baseUrl="baseUrl"
				:showHelp="showHelp"
				:newFields="newFields"
				@form-field-event="(data: FieldEventData) => emits('form-field-event', data)"
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
import { Button, Message, InputGroup, ToggleSwitch, InputGroupAddon, InputText, InputNumber, Select, DatePicker, MultiSelect, Tag } from 'primevue';
import FormField from '@primevue/forms/formfield';
import LeafletPicker from './LeafletPicker.vue';
import ArrayField from './ArrayField.vue';
import ColorField from './ColorField.vue';
import TestUrlButton from './TestUrlButton.vue';
import { isoToDate, dateToIso } from './FormDates';
import { isVisible } from './FormVisibility';
import { computed, nextTick, onMounted, toRaw, watch } from 'vue';
export interface PropsType {
	field: any
	// pass the v-slot="$form" to this prop
	formContext: any
	fieldNameWidth?: string
	/** where the API is, for a field's Test button */
	baseUrl?: string
	/** show the field's `description` under it (BasicForm's `showHelp`) */
	showHelp?: boolean
	/** the names of the fields the stored document lacks (BasicForm's `showChanges`): they are tagged "new" */
	newFields?: Set<string>
}
export interface SchemaChangeData {
	type: 'schema-change'
	field: any
	selected: any
}
/** a field that is not a PrimeVue control hands its new value to the form */
export interface SetValueData {
	type: 'set-value'
	field: any
	value: unknown
}
export type FieldEventData = SchemaChangeData | SetValueData
export interface EmitsType {
	(e: 'form-field-event', data: FieldEventData): void
}

const props = withDefaults(defineProps<PropsType>(), { showHelp: true })
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
// a link opens in a new tab and only to a secure address (the descriptor is ours, but a page is not built from what it holds without a look)
const safeLink = computed(() => {
	const link = props.field.link
	return link && typeof link.label === 'string' && /^https:\/\/[^\s]+$/.test(String(link.url)) ? link : null
})
const isInvalid = computed(() => !!fieldState.value.invalid);
const isNew = computed(() => props.newFields?.has(props.field.name) === true);
/** A field that is shown with no value takes its default: it was hidden when the document was saved (stored as null), or the document is older than the field. It is then there to see and change, not an error to find. */
function takeDefault() {
	const dflt = props.field.default
	if(props.field.type === 'header' || dflt === undefined || dflt === null) return
	const held = fieldState.value?.value
	if(held === null || held === undefined) emits('form-field-event', { type: 'set-value', field: props.field, value: structuredClone(toRaw(dflt)) })
}
watch(visible, now => { if(now) nextTick(takeDefault) })
onMounted(() => nextTick(takeDefault))
// a field as tall as a map or a list of rows: its label sits at the top, beside the first line, not in the middle of the block
const tall = computed(() => props.field.type === 'location' || props.field.type === 'array');
// a multi-select's choices: fixed ones as `{ name, value }`, like a lookup's list
const choices = computed(() => props.field.items?.enum ? props.field.items.enum.map((v: string) => ({ name: v, value: v })) : (props.field.list ?? []));
// a problem with one row of a list is shown on that row (by `ArrayField`); the message under the field is for the field as a whole
const errorMessage = computed(() => {
	const errors: { message?: string, path?: string[] }[] = fieldState.value.errors ?? []
	// a multi-select has no rows: a problem with one of its values is shown under it
	if (props.field.items?.type === 'string') return errors[0]?.message ?? fieldState.value.error?.message
	return errors.length > 0 ? errors.find(e => !e.path?.length)?.message : fieldState.value.error?.message
});
</script>
<style scoped>
/* the label keeps its width: a wide row editor beside it must not squeeze it until its text spills over the border */
.field-label {
	flex: 0 0 auto;
}
.new-tag {
	margin-left: .4rem;
	vertical-align: middle;
}
.label-top {
	align-items: flex-start;
}
</style>