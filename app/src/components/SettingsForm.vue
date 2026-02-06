<template>
	<BasicForm ref="bf" :form :initialValues :baseUrl="baseUrl" @validate="handleValidate" @submit="submitForm">
		<template #empty>
			<p v-if="initialValues" style="margin:auto">No Settings defined.</p>
		</template>
		<template #header>
			<Toolbar style="width:100%" class="p-1 mt-2">
				<template #start>
					<div style="font-weight: bold;font-size:150%">{{ title }}</div>
				</template>
				<template #center>
					<slot name="tb-center"></slot>
				</template>
				<template #end>
					<InputGroup>
						<Button size="small" icon="pi pi-check" severity="success" :disabled="submitDisabled" @click="submit" />
						<Button size="small" icon="pi pi-times" severity="danger" @click="reset" />
					</InputGroup>
				</template>
			</Toolbar>
			<slot name="header-end"></slot>
		</template>
	</BasicForm>
</template>
<script setup lang="ts">
import { ref, watch, nextTick } from "vue"
import BasicForm from "./BasicForm.vue"
import type { FormDef, ValidateEventData } from "./BasicForm.vue"
import { InputGroup, Button, Toolbar } from 'primevue';

export interface PropsType {
	title?: string
	baseUrl: string
	settingsUrl: string
	schemaUrl?: string
	schema?: any
}
export type SubmitEventData = {
	result: unknown|null
	invalid: unknown|null
	error: unknown|null
}
export interface EmitsType {
	(e: 'validate', data: ValidateEventData): void
	(e: 'submit', data: SubmitEventData): void
	(e: 'reset', data: any): void
	(e: 'load-settings', data: any): void
	(e: 'load-schema', data: any): void
}
const props = defineProps<PropsType>()
const emits = defineEmits<EmitsType>()
const form = ref<FormDef>()
const bf = ref<InstanceType<typeof BasicForm>>()
const initialValues = ref()
const submitDisabled = ref(true)
let _rev:string|undefined = undefined
let _id:string|undefined = undefined
let _schema:string|undefined = undefined

watch(() => props.settingsUrl, (nv) => {
	if(nv) {
		fetch(nv).then(rx => rx.json()).then(data => {
			console.log("settings", data)
			_rev = data._rev
			_id = data._id
			_schema = data._schema
			nextTick().then(_ => {
				initialValues.value = data
				emits("load-settings", data)
			})
		})
	}
}, { immediate: true })
watch(() => props.schemaUrl, (nv) => {
	if(nv) {
		fetch(nv).then(rx => rx.json()).then(data => {
			console.log("schema.fetch", data)
			form.value = data
			emits("load-schema", data)
		})
		.catch(ex => {
			console.error("schema.fetch.unhandled", ex)
			emits("load-schema", ex)
		})
	}
}, { immediate: true })
watch(() => props.schema, (nv) => {
	if(nv) {
		console.log("schema", nv)
		try {
		form.value = nv
		emits("load-schema", nv)
		}
		catch(ex) {
			console.error("schema.unhandled", ex)
			emits("load-schema", ex)
		}
	}
}, { immediate: true })
const handleValidate = (ved: ValidateEventData) => {
	console.log("validate", ved)
	submitDisabled.value = !ved.result.success
	emits("validate", ved)
}
const submitForm = (data:any) => {
	console.log("submitForm", data)
	if(data.data.valid) {
		// result.data has only the validated fields
		const post = structuredClone(data.result.data)
		if(_rev) {
			post._rev = _rev
		}
		if(_id) {
			post._id = _id
		}
		if(_schema) {
			post._schema = _schema
		}
		fetch(props.settingsUrl, {
			method: "PUT",
			headers: {
				"Content-Type": "application/json"
			},
			body: JSON.stringify(post)
		})
		.then(rx => {
			if(!rx.ok) {
				throw new Error(`Error ${rx.status}: ${rx.statusText}`)
			}
			return rx.json()
		})
		.then(jv => {
			console.log("submitForm.result", jv)
			if(jv.success) {
				_rev = jv.rev
			}
			emits("submit", {result: jv, invalid: null, error: null})
		})
		.catch(ex => {
			console.error("submitForm.unhandled", ex)
			emits("submit", { result: null, invalid: null, error: ex })
		})
	}
	else {
		console.warn("submitForm.invalid", data)
		emits("submit", { result: null, error: null, invalid: data })
	}
}
const reset = () => {
	bf.value?.reset()
	emits("reset", null)
}
const submit = () => {
	bf.value?.submit()
}
defineExpose({ submit, reset })
</script>
<style scoped>
</style>