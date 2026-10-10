<template>
	<BasicForm ref="bf" :form :initialValues :baseUrl="baseUrl" @validate="handleValidate" @submit="submitForm">
		<template #empty>
			<p style="margin:auto">No Settings defined.</p>
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
			<Message v-if="conflict" severity="warn" :closable="false" class="mt-1">
				<div class="flex align-items-center gap-2 flex-wrap">
					<span>{{ conflict.message }}</span>
					<Button size="small" label="Reload" icon="pi pi-refresh" severity="secondary" @click="reload" />
					<Button size="small" label="Overwrite" icon="pi pi-upload" severity="danger" @click="overwrite" />
				</div>
			</Message>
			<slot name="header-end"></slot>
		</template>
	</BasicForm>
</template>
<script setup lang="ts">
import { apiJson, apiPut, ApiError } from "./ApiClient"
import { ref, watch, nextTick, onMounted, onBeforeUnmount } from "vue"
import { onBeforeRouteLeave } from "vue-router"
import { useConfirm } from "primevue/useconfirm"
import BasicForm from "./BasicForm.vue"
import type { ValidateEventData } from "./BasicForm.vue"
import type { FormDef } from "./FormDefs"
import { InputGroup, Button, Toolbar, Message } from 'primevue';

export interface PropsType {
	title?: string
	baseUrl: string
	settingsUrl: string
	settings?: any
	schema: any
}
export type SubmitEventData = {
	result: unknown|null
	invalid: unknown|null
	error: unknown|null
	/** the form has shown the problem itself (a conflict message); do not also toast it */
	handled?: boolean
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
const conflict = ref<{ message: string, rev: string|undefined }|null>(null)
let lastPost: any = undefined
let _rev:string|undefined = undefined
let _id:string|undefined = undefined
let _schema:string|undefined = undefined

watch(() => props.settings, (nv) => {
	if(nv) {
		_rev = nv._rev
		_id = nv._id
		_schema = nv._schema
		nextTick().then(_ => {
			initialValues.value = nv
			emits("load-settings", nv)
		})
	}
	else {
		_rev = undefined
		_id = undefined
		_schema = undefined
		initialValues.value = undefined
		emits("load-settings", undefined)
	}
}, { immediate: true })
watch(() => props.schema, (nv) => {
	if(nv) {
		try {
			form.value = nv
			emits("load-schema", nv)
		}
		catch(ex) {
			console.error("schema.unhandled", ex)
			emits("load-schema", ex)
		}
	}
	else {
		form.value = undefined
		emits("load-schema", undefined)
	}
}, { immediate: true })
const handleValidate = (ved: ValidateEventData) => {
	submitDisabled.value = !ved.result.success
	emits("validate", ved)
}
function applySettings(nv: any) {
	_rev = nv._rev
	_id = nv._id
	_schema = nv._schema
	initialValues.value = nv
	emits("load-settings", nv)
}
function send(post: any) {
	lastPost = post
	conflict.value = null
	apiPut(props.settingsUrl, post)
	.then(jv => {
		if(jv.success) {
			_rev = jv.rev
			// what was saved is the new starting point: the form is no longer "changed" (leaving does not ask), and secrets show masked again
			apiJson(props.settingsUrl).then(applySettings).catch(ex => console.warn("settings.reload", ex))
		}
		emits("submit", { result: jv, invalid: null, error: null })
	})
	.catch(ex => {
		if(ex instanceof ApiError && ex.status === 409) {
			// somebody else saved first: let the user choose between their copy and ours
			conflict.value = { message: ex.message, rev: typeof ex.body?.rev === "string" ? ex.body.rev : undefined }
			emits("submit", { result: null, invalid: null, error: ex, handled: true })
		}
		else if(ex instanceof ApiError && ex.status === 422 && Array.isArray(ex.body?.errors)) {
			// each problem goes on its field
			bf.value?.setServerErrors(ex.body.errors)
			emits("submit", { result: null, invalid: null, error: ex })
		}
		else {
			console.error("submitForm.unhandled", ex)
			emits("submit", { result: null, invalid: null, error: ex })
		}
	})
}
/** Drop the edits and show what the server has now. */
const reload = () => {
	apiJson(props.settingsUrl)
	.then(doc => {
		conflict.value = null
		applySettings(doc)
	})
	.catch(ex => emits("submit", { result: null, invalid: null, error: ex }))
}
/** Save the edits over what the server has now. */
const overwrite = () => {
	if(!lastPost || !conflict.value?.rev) return
	send({ ...lastPost, _rev: conflict.value.rev })
}
const confirm = useConfirm()
const leaving = (): boolean|Promise<boolean> => {
	if(!bf.value?.isDirty) return true
	return new Promise(resolve => {
		confirm.require({
			header: "Unsaved changes",
			message: "Leave this page and discard your changes?",
			icon: "pi pi-exclamation-triangle",
			acceptLabel: "Discard",
			rejectLabel: "Stay",
			accept: () => resolve(true),
			reject: () => resolve(false),
		})
	})
}
onBeforeRouteLeave(leaving)
const warnBeforeClose = (e: BeforeUnloadEvent) => {
	if(bf.value?.isDirty) {
		e.preventDefault()
	}
}
onMounted(() => window.addEventListener("beforeunload", warnBeforeClose))
onBeforeUnmount(() => window.removeEventListener("beforeunload", warnBeforeClose))
const submitForm = (data:any) => {
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
		send(post)
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