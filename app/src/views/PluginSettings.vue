<template>
	<div class="flex flex-column gap-2 mt-1 p-1" style="width:80%;margin:auto">
		<BasicForm ref="bf" :form="form" :baseUrl="API_URL" :initialValues class="form" @validate="handleValidate" @submit="submitForm">
			<template #empty>
				<p style="margin:auto">No Plugin Settings defined.</p>
			</template>
			<template #header>
				<Toolbar style="width:100%" class="p-1 mt-2">
					<template #start>
						<div style="font-weight: bold;font-size:150%">Plugin Settings</div>
					</template>
					<template #center>
						<Select :options="plugins" v-model="selectedPlugin" style="width:20rem">
							<template #value="slotProps">
								<div v-if="slotProps.value">{{ slotProps.value.id }} ({{ slotProps.value.version }})</div>
							</template>
							<template #option="slotProps">
								<div class="flex flex-column">
									<div>{{ slotProps.option.id }} ({{ slotProps.option.version }})</div>
									<div style="max-width:17rem">{{ slotProps.option.description }}</div>
								</div>
							</template>
						</Select>
					</template>
					<template #end>
						<InputGroup>
							<Button size="small" icon="pi pi-check" severity="success" :disabled="submitDisabled" @click="handleSubmit" />
							<Button size="small" icon="pi pi-times" severity="danger" @click="handleReset" />
						</InputGroup>
					</template>
				</Toolbar>
				<div v-if="selectedPlugin" class="m-3" style="display:grid;width:100%;place-items:center;grid-template-columns: repeat(5,1fr);grid-template-rows:repeat(2,fr)">
					<div class="plugin-label" style="grid-row:1;grid-column:1">id</div>
					<div style="grid-row:2;grid-column:1">{{ selectedPlugin.id }}</div>
					<div class="plugin-label" style="grid-row:1;grid-column:2">version</div>
					<div style="grid-row:2;grid-column:2">{{ selectedPlugin.version }}</div>
					<div class="plugin-label" style="grid-row:1;grid-column:3">enabled</div>
					<div style="grid-row:2;grid-column:3"><i class="pi" :class="selectedPlugin.disabled ? 'pi-times' : 'pi-check'"></i></div>
					<div class="plugin-label" style="grid-row:1;grid-column:4">description</div>
					<div style="grid-row:2;grid-column:4">{{ selectedPlugin.description }}</div>
					<div class="plugin-label" style="grid-row:1;grid-column:5">features</div>
					<div v-if="selectedPlugin.features" class="flex flex-row" style="grid-row:2;grid-column:5">
						<template v-for="feature in selectedPlugin.features">
							<Tag class="mr-1 ml-1" :value="feature">{{ feature }}</Tag>
						</template>
					</div>
					<div v-else>-</div>
				</div>
			</template>
			<template #group-header="slotProps">
				<h3 class="mb-0">{{ slotProps.label }}</h3>
			</template>
		</BasicForm>
	</div>
</template>
<script setup lang="ts">
import BasicForm from "../components/BasicForm.vue"
import type {FormDef, ValidateEventData} from "../components/BasicForm.vue"
import { ref, onMounted, watch, nextTick } from "vue"
import { InputGroup, InputGroupAddon, Button, Message, Toolbar, Select, Tag } from 'primevue';
const form = ref<FormDef>()
const bf = ref<InstanceType<typeof BasicForm>>()
const initialValues = ref()
const plugins = ref([])
const selectedPlugin = ref(undefined)
const submitDisabled = ref(true)
const API_URL = import.meta.env.VITE_API_URL
let _rev:string|undefined = undefined
let _id:string|undefined = undefined
onMounted(() => {
	const listUrl = `${API_URL}/api/plugins/list`
	const px0 = fetch(listUrl).then(rx => rx.json())
	px0.then(json => {
		console.log("plugins", json)
		plugins.value = json
	})
	.catch(ex => {
		console.error("fetch.unhandled", ex)
	})
})
watch(selectedPlugin, (nv,ov) => {
	console.log("selectedPlugin", nv, ov)
	if(nv) {
		form.value = nv.settings
		const settingsUrl = `${API_URL}/api/plugins/${nv.id}/settings`
		const px0 = fetch(settingsUrl).then(rx => rx.json())
		px0.then(json => {
			console.log("plugin settings", json)
			_rev = json._rev
			_id = json._id
			nextTick().then(_ => {
				initialValues.value = json
				bf.value?.reset()
			})
		})
	}
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
		const settingsUrl = `${API_URL}/api/plugins/${selectedPlugin.value.id}/settings`
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
.plugin-label {
	font-weight: bold;
	font-size: 120%;
}
</style>