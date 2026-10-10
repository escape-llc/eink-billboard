<template>
	<div>
		<Form ref="form" v-slot="$form" class="flex flex-column gap-1 w-full sm:w-56" :initialValues="localValues" :resolver
			:validateOnValueUpdate="true" :validateOnBlur="true" @submit="handleSubmit">
			<slot name="header"></slot>
			<!--
			<div>{{  JSON.stringify(localProperties)  }}</div>
			-->
			<template v-if="localProperties.length === 0">
				<slot name="empty"></slot>
			</template>
			<template v-else>
				<slot name="before-fields"></slot>
				<template v-for="field in localProperties" :key="field.name">
					<!--
					<div>{{  JSON.stringify(field)  }}</div>
					-->
					<template v-if="field.type === 'header'">
						<slot name="group-header" v-bind="field">
							<div>{{ field.title }}</div>
						</slot>
					</template>
					<template v-else>
						<BasicFormField :field="field" :formContext="$form" :fieldNameWidth="fieldNameWidth" @form-field-event="handleFormFieldEvent">
						</BasicFormField>
					</template>
				</template>
				<slot name="after-fields"></slot>
			</template>
			<slot name="footer"></slot>
		</Form>
	</div>
</template>
<script setup lang="ts">
import { apiJson, joinUrl } from "./ApiClient"
//import { InputGroup, ToggleSwitch, InputGroupAddon, InputText, InputNumber, Message, Select } from 'primevue';
import Form from "@primevue/forms/form"
import { ref, toRaw, nextTick, watch, inject, computed } from "vue"
import z from "zod"
import BasicFormField from './BasicFormField.vue'
import { fieldRules, type FormField } from "./FormValidation"
import { hiddenNames } from "./FormVisibility"
import type { LookupValue, FormDef, SchemaType } from "./FormDefs"

const form = ref()
// the rules depend on the values (a hidden field is not validated), so they are built per validation
let currentResolver: ((values: Record<string, any>) => z.ZodTypeAny)|undefined = undefined;

type AddToSchemaType = (resv: Record<string, z.ZodTypeAny>) => void
type AddInitialValuesType = () => Record<string, any>

export interface PropsType {
	form?: FormDef
	initialValues?: any
	fieldNameWidth?: string
	baseUrl: string
	beforeFieldsSchema?: AddToSchemaType
	afterFieldsSchema?: AddToSchemaType
	addInitialValues?: AddInitialValuesType
}
export interface ValidateEventData {
	result: z.ZodSafeParseResult<any>
	values: any
}
export interface EmitsType {
	(e: 'validate', data: ValidateEventData): void
	(e: 'submit', data: any): void
}

const props = withDefaults(defineProps<PropsType>(), { fieldNameWidth: "10rem" })
const emits = defineEmits<EmitsType>()
const localProperties = ref<any[]>([])
const localValues = ref<any>({})
const injplugins = inject("settingsPluginsList", ref([]))
const injdataSources = inject("settingsDataSourcesList", ref([]))
const plugins = computed<any[]>(() => injplugins.value)
const dataSources = computed<any[]>(() => injdataSources.value)
watch(() => props.form, (nv) => {
	if(nv) {
		// a plugin just chosen brings fields the values do not have: they start at the descriptor's default, as they do for a new item
		applyDefaults(formProperties(nv.schema), localValues.value).forEach(([name, value]) => { localValues.value[name] = value })
		ensureInitializeForm(nv.schema)
	}
	else {
		localProperties.value = []
		currentResolver = undefined
	}
}, { immediate:true }
)
watch(() => props.initialValues, (nv) => {
	if(nv) {
		let ox = structuredClone(toRaw(nv))
		if(props.addInitialValues) {
			const addv = props.addInitialValues()
			ox = Object.assign(ox, addv) // ensure new object reference to trigger form update
		}
		// a value the document does not have yet starts at the descriptor's default (a new playlist track, say)
		const dflts = props.form?.schema ? applyDefaults(formProperties(props.form.schema), ox) : []
		dflts.forEach(([name, value]) => { ox[name] = value })
		localValues.value = ox
		ensureInitializeForm(props.form?.schema)
	}
	else {
		localValues.value = {}
	}
	nextTick().then(_ => {
		form.value?.reset();
		form.value?.validate();
	});
}, { immediate:true }
)
function ensureInitializeForm(schema: SchemaType|undefined): void {
	if(!schema) return;
	localProperties.value = formProperties(schema)
	currentResolver = createResolver(localProperties.value)
	startLookups(schema, localProperties.value)
}
function startLookups(schema: SchemaType, values: any[]): void {
	values.forEach(px => {
		if(px.lookup && px.listType === "url") {
			lookupUrl(px)
		}
		if(px.children) {
			startLookups(schema, px.children)
		}
	})
}
function schemaFilterFeatures(features: string[], check: string[]|undefined): boolean {
	if(!features || features.length === 0) return false;
	if(!check || check.length === 0) return true;
	return check.some(c => features.includes(c))
}
function formProperties(schema: SchemaType|undefined) :any[] {
	if(schema?.properties) {
		const retv:any[] = []
		schema.properties.forEach(px => {
			const fx:any = { ...px }
			if("lookup" in px && px.lookup) {
				if(isLookupItems(schema, px.lookup, "items")) {
					fx.list = lookupItems(schema, px.lookup)
					fx.listType = "items"
				}
				else if(isLookupItems(schema, px.lookup, "url")) {
					fx.list = []
					fx.listType = "url"
					const urlLookup = schema.lookups ? schema.lookups[px.lookup] : undefined
					fx.lookupUrl = toRaw(urlLookup && 'url' in urlLookup ? urlLookup.url : null)
				}
				else if(isLookupItems(schema, px.lookup, "schema")) {
					fx.list = lookupSchema(schema, px.lookup)
					fx.listType = "schema"
				}
				else {
					console.warn("Unknown lookup type", px.lookup)
				}
			}
			if(px.type === "schema" && "list" in fx && fx.listType === "schema") {
				const svalue = localValues.value[px.name]
				if(svalue) {
					const target = fx.list.find((vx: any) => vx.value === svalue)
					if(target) {
						fx.children = formProperties(target.schema?.schema as SchemaType|undefined)
					}
				}
			}
			retv.push(fx)
		})
		return retv
	}
	return []
}
function isLookupItems(schema: SchemaType, lookup:string, prop:string): boolean {
	if(schema.lookups) {
		const lookups = schema.lookups
		if(lookup in lookups) {
			const lku = lookups[lookup]
			if(lku && prop in lku) {
				return true
			}
		}
	}
	return false
}
function lookupItems(schema: SchemaType, lookup:string): LookupValue[] {
	if(schema.lookups) {
		const lookups = schema.lookups
		if(lookup in lookups) {
			const lku = lookups[lookup]
			if(lku && "items" in lku) {
				const items = toRaw(lku.items)
				const result = items.map(mx=>structuredClone(mx))
				return result
			}
		}
	}
	return []
}
function lookupSchema(schema: SchemaType, lookup:string): LookupValue[] {
 if(schema.lookups) {
		const lookups = schema.lookups
		if(lookup in lookups) {
			const lku = lookups[lookup]
			if(lku && "schema" in lku) {
				if(lku.schema === "plugins") {
					return plugins.value.filter(px => schemaFilterFeatures(px.features, lku.features)).map(px => ({ name: px.name, value: px.id, schema: toRaw(px.instanceSettings) }))
				}
				else if(lku.schema === "data-sources") {
					return dataSources.value.filter(px => schemaFilterFeatures(px.features, lku.features)).map(px => ({ name: px.name, value: px.id, schema: toRaw(px.instanceSettings) }))
				}
				else {
					console.warn("Unknown lookup schema", lku.schema)
				}
			}
		}
	}
	return [];
}
function lookupUrl(target: any): void {
	if(!target) return;
	if(!target.lookupUrl) return;
	const finalUrl = joinUrl(props.baseUrl, target.lookupUrl)
	//console.log("lookupUrl.start", finalUrl)
	apiJson(finalUrl).then(json => {
		//console.log("lookupUrl", json, target)
		nextTick().then(_ => {
			target.list = withCurrentValue(json, target.name)
			target.lookupError = undefined
		})
	})
	.catch(ex => {
		console.error("lookupUrl", ex)
		nextTick().then(_ => {
			// the message is shown under the field; it is never a choice that could be saved
			target.list = withCurrentValue([], target.name)
			target.lookupError = `The choices could not be loaded: ${ex.message}`
		})
	})
}
/** A stored value the list does not offer (renamed, or the list failed to load) must still show, not silently look unset. */
function withCurrentValue(list: LookupValue[], name: string): LookupValue[] {
	const current = localValues.value?.[name]
	if(current === undefined || current === null || current === "" || list.some(lx => lx.value === current)) return list
	return [...list, { name: String(current), value: current }]
}
function createResolver(fields: FormField[]): (values: Record<string, any>) => z.ZodTypeAny {
	return (values) => {
		const resv: Record<string, z.ZodTypeAny> = {}
		if(props.beforeFieldsSchema) {
			props.beforeFieldsSchema(resv)
		}
		fieldRules(fields, resv, values)
		if(props.afterFieldsSchema) {
			props.afterFieldsSchema(resv)
		}
		return z.object(resv)
	}
}
const serverErrors: Record<string, { message: string, value: string }> = {}
let lastSubmitted: Record<string, any> = {}
/** Show the `errors` of a 422 response (`[{ path: [name], message }]`) on their fields. Returns how many matched a field of this form. */
const setServerErrors = (errors: { path?: unknown[], message?: string }[]): number => {
	const values = lastSubmitted
	let matched = 0
	for(const e of errors ?? []) {
		const name = Array.isArray(e?.path) ? e.path[0] : undefined
		if(typeof name === "string" && typeof e.message === "string") {
			serverErrors[name] = { message: e.message, value: JSON.stringify(values?.[name]) }
			matched++
		}
	}
	nextTick().then(_ => form.value?.validate())
	return matched
}
const resolver = ({ values }: { values: Record<string, any> }) => {
	const errors:Record<PropertyKey,any> = {};
	if(!currentResolver) return { values, errors };
	const result = currentResolver(values).safeParse(values);
	if(!result.success) {
		result.error.issues.forEach(issue => {
			const field = issue.path[0];
			if(field !== undefined) {
				if (!errors[field]) errors[field] = [];
				errors[field].push({ message: issue.message });
			}
		});
	}
	// problems the server reported stay on a field until its value changes
	for(const [name, entry] of Object.entries(serverErrors)) {
		if(JSON.stringify(values[name]) !== entry.value) {
			delete serverErrors[name]
		}
		else if(!errors[name]) {
			errors[name] = [{ message: entry.message }]
		}
	}
	emits('validate', { result, values });
	return {
		values, // (Optional) Used to pass current form values to submit event.
		errors
	};
}
const handleSubmit = (data:any) => {
	lastSubmitted = data.values ?? {}
	const result = currentResolver?.(data.values)?.safeParse(data.values);
	if(result?.success) {
		// a hidden field is not applicable: it is saved as null
		const saved = result.data as Record<string, unknown>
		hiddenNames(localProperties.value, data.values).forEach(name => { saved[name] = null })
	}
	emits('submit', { result, data });
}
const submit = () => {
	form.value?.submit();
}
const reset = () => {
	form.value?.reset();
}
// function declarations, not consts: the `immediate` watches above run during setup, before a const here would be initialized
function flatNames(fields: FormField[]): string[] {
	return fields.flatMap(f => [...(f.type === "header" ? [] : [f.name]), ...flatNames(f.children ?? [])])
}
/** The field of that name at any depth (a data source's own fields can hold another choice). */
function findField(fields: FormField[], name: string): any {
	for(const f of fields) {
		if(f.name === name) return f
		const inner = findField(f.children ?? [], name)
		if(inner) return inner
	}
	return undefined
}
/** The `default` of each field (null and absent defaults carry no information), for values the form does not have yet. */
function applyDefaults(fields: FormField[], values: Record<string, any> = {}): [string, unknown][] {
	return fields.flatMap(f => [
		...(f.type !== "header" && f.default !== undefined && f.default !== null && !(f.name in values) ? [[f.name, f.default] as [string, unknown]] : []),
		...applyDefaults(f.children ?? [], values)
	])
}
const handleFormFieldEvent = (data:any) => {
	if(data.type === "schema-change") {
		const field = findField(localProperties.value, data.field.name)
		if(field) {
			// the previous choice's values must not be saved with the new one
			flatNames(field.children ?? []).forEach(name => form.value?.setFieldValue(name, null))
			const chosen = data.selected?.schema?.schema as SchemaType|undefined
			field.children = formProperties(chosen)
			applyDefaults(field.children).forEach(([name, value]) => form.value?.setFieldValue(name, value))
			currentResolver = createResolver(localProperties.value)
			startLookups(chosen as SchemaType, field.children)
			nextTick().then(_ => {
				form.value?.validate();
			})
		}
	}
}
const isDirty = computed(() => Object.values<{ dirty?: boolean }>(form.value?.states ?? {}).some(st => st.dirty))
defineExpose({ submit, reset, setServerErrors, isDirty })
</script>
<style scoped>
</style>