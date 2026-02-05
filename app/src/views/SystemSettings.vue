<template>
	<div style="width:100%">
		<BasicForm ref="bf" :form :initialValues :baseUrl="API_URL" class="form" @validate="handleValidate" @submit="submitForm">
			<template #header>
				<Toolbar style="width:100%" class="p-1 mt-2">
					<template #start>
						<div style="font-weight: bold;font-size:150%">System Settings</div>
					</template>
					<template #end>
						<InputGroup>
							<Button size="small" icon="pi pi-check" severity="success" :disabled="submitDisabled" @click="handleSubmit" />
							<Button size="small" icon="pi pi-times" severity="danger" @click="handleReset" />
						</InputGroup>
					</template>
				</Toolbar>
			</template>
		</BasicForm>
	</div>
</template>
<script setup lang="ts">
import BasicForm from "../components/BasicForm.vue"
import type {FormDef, ValidateEventData} from "../components/BasicForm.vue"
import { ref, onMounted, nextTick } from "vue"
import { InputGroup, InputGroupAddon, Button, Message, Toolbar, Select } from 'primevue';
const form = ref<FormDef>()
const bf = ref<InstanceType<typeof BasicForm>>()
const initialValues = ref()
const submitDisabled = ref(true)
const API_URL = import.meta.env.VITE_API_URL
let _rev:string|undefined = undefined
let _id:string|undefined = undefined
const settingsUrl = `${API_URL}/api/settings/system`
onMounted(() => {
	const schemaUrl = `${API_URL}/api/schemas/system`
	const px0 = fetch(schemaUrl).then(rx => rx.json())
	const px1 = fetch(settingsUrl).then(rx => rx.json())
	Promise.all([px0,px1])
	.then(pxs => {
		console.log("schema,settings", pxs[0], pxs[1])
		form.value = pxs[0]
		_rev = pxs[1]._rev
		_id = pxs[1]._id
		nextTick().then(_ => {
			initialValues.value = pxs[1]
		})
	})
	.catch(ex => {
		console.error("fetch.unhandled", ex)
	})
})
const handleValidate = (e: ValidateEventData) => {
	console.log("validate", e)
	submitDisabled.value = !e.result.success
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
		fetch(settingsUrl, {
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
		})
		.catch(ex => {
			console.error("submitForm.unhandled", ex)
		})
	}
	else {
		console.warn("submitForm.invalid", data)
	}
}
const handleReset = () => {
	bf.value?.reset()
}
const handleSubmit = () => {
	bf.value?.submit()
}
</script>
<style scoped>
.form {
	width: 50%;
	margin: auto;
}
</style>