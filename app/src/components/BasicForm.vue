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
							<div>{{ field.label }}</div>
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
import type { LookupValue, FormDef, SchemaType } from "./FormDefs"

const form = ref()
let currentResolver: z.ZodTypeAny|undefined = undefined;

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
		ensureInitializeForm(nv.schema, localValues.value)
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
		localValues.value = ox
		ensureInitializeForm(props.form?.schema as SchemaType, localValues.value)
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
function ensureInitializeForm(schema: SchemaType, values: any): void {
	if(values && Object.keys(values).length === 0) return;
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
function formProperties(schema: SchemaType) :any[] {
	if(schema.properties) {
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
						fx.children = formProperties(target.schema.schema as SchemaType)
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
			target.list = json
		})
		// TODO add an entry corresponding to current value if missing
	})
	.catch(ex => {
		console.error("lookupUrl", ex)
		nextTick().then(_ => {
			target.list = [{name:ex.message,value:ex.message}]
		})
		// TODO add an entry corresponding to current value if missing
	})
}
function createResolver(fields: FormField[]): z.ZodTypeAny {
	const resv: Record<string, z.ZodTypeAny> = {}
	if(props.beforeFieldsSchema) {
		props.beforeFieldsSchema(resv)
	}
	fieldRules(fields, resv)
	if(props.afterFieldsSchema) {
		props.afterFieldsSchema(resv)
	}
	return z.object(resv)
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
	const result = currentResolver.safeParse(values);
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
	const result = currentResolver?.safeParse(data.values);
	emits('submit', { result, data });
}
const submit = () => {
	form.value?.submit();
}
const reset = () => {
	form.value?.reset();
}
const handleFormFieldEvent = (data:any) => {
	if(data.type === "schema-change") {
		const field = localProperties.value.find((f:any) => f.name === data.field.name)
		if(field) {
			field.children = formProperties(data.selected.schema.schema)
			currentResolver = createResolver(localProperties.value)
			startLookups(data.selected.schema.schema, field.children)
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