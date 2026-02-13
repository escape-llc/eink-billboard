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
			<template v-else v-for="field in localProperties" :key="field.name">
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
			<slot name="footer"></slot>
		</Form>
	</div>
</template>
<script setup lang="ts">
//import { InputGroup, ToggleSwitch, InputGroupAddon, InputText, InputNumber, Message, Select } from 'primevue';
import Form from "@primevue/forms/form"
import { ref, toRaw, nextTick, watch, inject, computed } from "vue"
import z from "zod"
import BasicFormField from './BasicFormField.vue'
import type { LookupValue, FormDef, SchemaType, PropertiesDef } from "./FormDefs"

const form = ref()
let currentResolver: z.ZodTypeAny|undefined = undefined;

export interface PropsType {
	form?: FormDef
	initialValues?: any
	fieldNameWidth?: string
	baseUrl: string
}
export interface ValidateEventData {
	result: z.ZodSafeParseResult<any>
	values: any
}
export interface EmitsType {
	(e: 'validate', data: ValidateEventData): void
	(e: 'submit', data: any): void
}

z.config({
	customError: (issue)=> {
		if (issue.code === "invalid_type" && (issue.input === null || issue.input === undefined)) {
			return "Required";
		}
		return undefined;
	}
});
const nullableAndEmptyStringSchema = z.preprocess(
  (val) => (val === "" ? null : val),
  z.string().nullable()
);
const nulableAndEmptyDateSchema = z.preprocess(
  (arg) => (arg === "" ? null : arg), // Convert "" to null
  z.iso.date().nullable()    // Then allow null or a valid ISO date
);

const props = withDefaults(defineProps<PropsType>(), { fieldNameWidth: "10rem" })
const emits = defineEmits<EmitsType>()
const localProperties = ref<any[]>([])
const localValues = ref<any>({})
const injplugins = inject("settingsPluginsList", ref([]))
const injdataSources = inject("settingsDataSourcesList", ref([]))
const plugins = computed<any[]>(() => injplugins.value)
const dataSources = computed<any[]>(() => injdataSources.value)
watch(() => props.form, (nv,ov) => {
	console.log("watch.form", nv, ov);
	if(nv) {
		ensureInitializeForm(nv.schema, localValues.value)
	}
	else {
		localProperties.value = []
		currentResolver = undefined
	}
}, { immediate:true }
)
watch(() => props.initialValues, (nv,ov) => {
	console.log("watch.initialValues", nv, ov);
	if(nv) {
		localValues.value = structuredClone(toRaw(nv))
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
	console.log("ensureInitializeForm", schema, values);
	if(values && Object.keys(values).length === 0) return;
	if(!schema) return;
	console.log("ensureInitializeForm.fire");
	localProperties.value = formProperties(schema)
	currentResolver = createResolver(schema, localProperties.value)
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
					fx.lookupUrl = toRaw(schema.lookups ? schema.lookups[px.lookup].url : null)
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
				console.log("formProperties.schema", px.name, svalue, fx.list)
				if(svalue) {
					const target = fx.list.find(vx => vx.value === svalue)
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
	const finalUrl = `${props.baseUrl}${target.lookupUrl}`
	console.log("lookupUrl.start", finalUrl)
	fetch(finalUrl).then(rx => rx.json()).then(json => {
		console.log("lookupUrl", json, target)
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
function schemaFor(px: PropertiesDef): z.ZodTypeAny|undefined {
	if(!px) return undefined;
	switch(px.type) {
		case "header":
			return undefined
		case "string":
			if(px.required === true) {
				return z.string().min(1, { error:"Required" })
			}
			else {
				return nullableAndEmptyStringSchema
			}
		case "boolean":
			let r2 = z.boolean()
			return r2
		case "number":
			let r4 = z.number()
			if(px.min) {
				r4 = r4.min(px.min, { error:`Minimum ${px.min}` })
			}
			if(px.max) {
				r4 = r4.max(px.max, { error:`Maximum ${px.max}` })
			}
			// for number this must go on the end
			if(px.required === true) {
				let r5 = r4.nonoptional()
				return r5
			}
			else {
				return r4
			}
		case "location":
			let r6 = z.object({ latitude: z.number(), longitude: z.number() })
			if(px.required === true) {
				let r7 = r6.nonoptional()
				return r7
			}
			else {
				return r6
			}
		case "schema":
			// TODO enforce value is in the schema list
			let r8 = z.string()
			if(px.required === true) {
				r8 = r8.min(1, { error:"Required" })
			}
			return r8
		case "date":
			if(px.required === true) {
				const strictlyRequired = z.preprocess((val) => {
					// Fix missing seconds for HTML inputs
					if (typeof val === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(val)) {
						return `${val}:00`;
					}
					return val;
				}, z.iso.date());
				return strictlyRequired
			}
			else {
				return nulableAndEmptyDateSchema
			}
		default:
			console.warn("no validation for type, using 'string'", px)
			let r3 = z.string()
			if(px.required === true) {
				r3 = r3.min(1, { error:"Required" })
			}
			return r3
	}
}
function createResolver(schema: SchemaType, values: any[]): z.ZodTypeAny {
	const resv: Record<string, z.ZodTypeAny> = {}
	function recursiveBit(props: PropertiesDef[]): void {
		props.forEach(px => {
			const sx = schemaFor(px)
			console.log("schemaFor", px.name, sx)
			if(sx) {
				resv[px.name] = sx
			}
			if(px.type === "schema" && "lookup" in px && px.lookup) {
				const target = values.find(vx => vx.name === px.lookup)
				if(target) {
					console.log("recursive.schema", px.lookup, target.children)
					if(target.children) {
						recursiveBit(target.children)
					}
				}
			}
		})
	}
	recursiveBit(schema.properties)
	return z.object(resv)
}
const resolver = ({ values }) => {
	const errors:Record<PropertyKey,any> = {};
	console.log("resolver", values, currentResolver)
	if(!currentResolver) return { values, errors };
	const result = currentResolver.safeParse(values);
	console.log("resolver", values, result);
	if(!result.success) {
		result.error.issues.forEach(issue => {
			const field = issue.path[0];
			if(field !== undefined) {
				if (!errors[field]) errors[field] = [];
				errors[field].push({ message: issue.message });
			}
		});
	}
	console.log("resolver.errors", errors);
	emits('validate', { result, values });
	return {
		values, // (Optional) Used to pass current form values to submit event.
		errors
	};
}
const handleSubmit = (data:any) => {
	console.log("handleSubmit", data);
	const result = currentResolver?.safeParse(data.values);
	console.log("handleSubmit.validate", result);
	emits('submit', { result, data });
}
const submit = () => {
	form.value?.submit();
}
const reset = () => {
	form.value?.reset();
}
const handleFormFieldEvent = (data:any) => {
	console.log("handleFormFieldEvent", data)
	if(data.type === "schema-change") {
		const field = localProperties.value.find((f:any) => f.name === data.field.name)
		if(field) {
			field.children = formProperties(data.selected.schema.schema)
			currentResolver = createResolver(props.form.schema, localProperties.value)
			startLookups(data.selected.schema.schema, field.children)
			nextTick().then(_ => {
				form.value?.validate();
			})
		}
	}
}
defineExpose({ submit, reset })
</script>
<style scoped>
</style>