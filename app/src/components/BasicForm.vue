<template>
	<div>
		<Form ref="form" v-slot="$form" class="flex flex-column gap-1 w-full sm:w-56" :initialValues="localValues" :resolver
			:validateOnValueUpdate="true" :validateOnBlur="true" @submit="handleSubmit">
			<slot name="header"></slot>
			<template v-if="localProperties.length === 0">
				<slot name="empty"></slot>
			</template>
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
					<InputGroup>
						<InputGroupAddon>
							<label :style="{'width': props.fieldNameWidth, 'max-width': props.fieldNameWidth }" style="flex-shrink:0;flex-grow:1" :for="field.name">{{ field.label }}</label>
						</InputGroupAddon>
						<template v-if="field.type === 'boolean'">
							<InputGroupAddon style="flex-grow:1">
								<ToggleSwitch :name="field.name" size="small" fluid />
							</InputGroupAddon>
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
					<Message v-if="$form[field.name]?.invalid" severity="error" size="small" variant="simple">{{ $form[field.name].error?.message }}</Message>
				</template>
			</template>
			<slot name="footer"></slot>
		</Form>
	</div>
</template>
<script setup lang="ts">
import { InputGroup, ToggleSwitch, InputGroupAddon, InputText, InputNumber, Message, Select } from 'primevue';
import Form from "@primevue/forms/form"
import FormField from "@primevue/forms/formfield"
import { ref, toRaw, nextTick, watch } from "vue"
import z from "zod"
import LeafletPicker from './LeafletPicker.vue';

const form = ref()
let currentResolver: z.ZodTypeAny|undefined = undefined;

export type FieldGroupDef = {
	name: string
	label: string
	type: "header"
}
export type FieldDef = {
	name: string
	label: string
	type: "string" | "boolean" | "number" | "int" | "location"
	required: boolean
	lookup?: string
	min?: number
	max?: number
	step?: number
	minFractionDigits?:number
	maxFractionDigits?:number
}
export type LookupUrl = {
	url: string
}
export type LookupValue = {
	name: string;
	value: unknown;
}
export type LookupItems = {
	items: LookupValue[]
}
export type LookupDef = LookupItems | LookupUrl

export type FormDef = {
	schema: SchemaType
	default: Record<string,any>
}
export type PropertiesDef = FieldDef | FieldGroupDef
export type SchemaType = {
	lookups: Record<string,LookupDef>
	properties: PropertiesDef[]
}
export interface PropsType {
	form?: FormDef
	initialValues?: any
	fieldNameWidth?: string
	baseUrl?: string
}
export interface ValidateEventData {
	result: z.ZodSafeParseResult<any>
	values: any
}
export interface EmitsType {
	(e: 'validate', data: ValidateEventData): void
	(e: 'submit', data: any): void
}
const props = withDefaults(defineProps<PropsType>(), { fieldNameWidth: "10rem", baseUrl: "" })
const emits = defineEmits<EmitsType>()
const localProperties = ref<any[]>([])
const localValues = ref<any>({})
watch(() => props.form, (nv,ov) => {
	console.log("watch.form", nv, ov);
	if(nv) {
		localProperties.value = formProperties(nv)
		currentResolver = createResolver(nv)
		startLookups(nv)
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
function startLookups(form: FormDef): void {
	form.schema.properties.forEach(px => {
		const target = localProperties.value.find(lp => lp.name === px.name)
		if(target && target.lookup && target.listType === "url") {
			lookupUrl(form, target.lookup, target)
		}
	})
}
function formProperties(form: FormDef) {
	if(form.schema.properties) {
		const retv:any[] = []
		form.schema.properties.forEach(px => {
			const fx:any = { ...px }
			if("lookup" in px && px.lookup && isLookupItems(form, px.lookup, "items")) {
				fx.list = lookupItems(form, px.lookup)
				fx.listType = "items"
			}
			else if("lookup" in px && px.lookup && isLookupItems(form, px.lookup, "url")) {
				fx.list = []
				fx.listType = "url"
			}
			retv.push(fx)
		})
		return retv
	}
	return []
}
function isLookupItems(form: FormDef, lookup:string, prop:string): boolean {
	if(form.schema.lookups) {
		const lookups = form.schema.lookups
		if(lookup in lookups) {
			const lku = lookups[lookup]
			if(lku && prop in lku) {
				return true
			}
		}
	}
	return false
}
function lookupItems(form: FormDef, lookup:string): LookupValue[] {
	if(form.schema.lookups) {
		const lookups = form.schema.lookups
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
function lookupUrl(form: FormDef, lookup: string, target: any): void {
	if(!target) return;
	if(form.schema.lookups) {
		const lookups = form.schema.lookups
		if(lookup in lookups) {
			const lku = lookups[lookup]
			if(lku && "url" in lku) {
				const url = toRaw(lku.url)
				const finalUrl = `${props.baseUrl}${url}`
				console.log("lookupUrl", url, props.baseUrl, target)
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
		}
	}
}
function createResolver(form: FormDef): z.ZodTypeAny {
	const resv: Record<string, z.ZodTypeAny> = {}
	form.schema.properties.forEach(px => {
		switch(px.type) {
			case "header":
				break
			case "string":
				let r1 = z.string()
				if(px.required === true) {
					r1 = r1.min(1, { error:"Required" })
				}
				resv[px.name] = r1
				break
			case "boolean":
				let r2 = z.boolean()
				resv[px.name] = r2
				break
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
					resv[px.name] = r5
				}
				else {
					resv[px.name] = r4
				}
				break
			case "location":
				let r6 = z.object({ latitude: z.number(), longitude: z.number() })
				if(px.required === true) {
					let r7 = r6.nonoptional()
					resv[px.name] = r7
				}
				else {
					resv[px.name] = r6
				}
				break;
			default:
				console.warn("no validation for type, using 'string'", px)
				let r3 = z.string()
				if(px.required === true) {
					r3 = r3.min(1, { error:"Required" })
				}
				resv[px.name] = r3
				break;
		}
	})
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
defineExpose({ submit, reset })
</script>
<style scoped>
</style>