<template>
	<BasicForm ref="bf" :form :initialValues fieldNameWidth="adaptive" :baseUrl="baseUrl" :owner="owner" :showHelp="showHelp" :showChanges="true" @validate="handleValidate" @submit="submitForm">
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
						<Button v-if="defaults" size="small" icon="mi mi-settings-backup-restore" label="Restore defaults" severity="secondary" title="Put back the factory text of every field (then save)" @click="restoreAll" />
						<HelpToggle v-model="showHelp" />
						<Button size="small" icon="mi mi-check" severity="success" :disabled="submitDisabled" @click="submit" />
						<Button size="small" icon="mi mi-close" severity="danger" @click="reset" />
					</InputGroup>
				</template>
			</Toolbar>
			<Message size="small" v-if="conflict" severity="warn" :closable="false" class="mt-1">
				<div class="flex align-items-center gap-2 flex-wrap">
					<span>{{ conflict.message }}</span>
					<Button size="small" label="Reload" icon="mi mi-refresh" severity="secondary" @click="reload" />
					<Button size="small" label="Overwrite" icon="mi mi-upload" severity="danger" @click="overwrite" />
				</div>
			</Message>
			<slot name="header-end"></slot>
		</template>
	</BasicForm>
</template>
<script setup lang="ts">
import { ApiError } from "./ApiClient"
import { api } from "../api/client"
import { ref, watch, nextTick, onMounted, onBeforeUnmount, provide } from "vue"
import { onBeforeRouteLeave } from "vue-router"
import { useConfirm } from "primevue/useconfirm"
import BasicForm from "./BasicForm.vue"
import HelpToggle from "./HelpToggle.vue"
import type { Owner, ValidateEventData } from "./BasicForm.vue"
import type { FormDef } from "./FormDefs"
import { InputGroup, Button, Toolbar, Message } from 'primevue';
// the fields' help text, shown until hidden (for the page's life)
const showHelp = ref(true)

export interface PropsType {
	title?: string
	baseUrl: string
	/** whose settings: a device-wide document by name, or a plugin's or data source's own (none until one is chosen) */
	target?: SettingsTarget
	settings?: any
	schema: any
	/** the plugin or data source whose settings these are: a `settings` lookup of a field chooses from its stored lists */
	owner?: Owner
	/** a device-wide document's factory values (the copy shipped in the NVE) can be put back, by a field or the whole form, for the user to save or not */
	defaults?: boolean
}
export type SettingsTarget = { kind: "device", name: string } | { kind: "plugin" | "datasource", id: string }
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
/** The stored document (secrets masked), from the target's route. */
function fetchDocument() {
	const target = props.target
	if(!target) return Promise.reject(new Error("Choose one first."))
	if(target.kind === "device") return api.get("/api/settings/{name}", { path: { name: target.name } })
	if(target.kind === "plugin") return api.get("/api/plugins/{plugin_id}/settings", { path: { plugin_id: target.id } })
	return api.get("/api/datasources/{datasource_id}/settings", { path: { datasource_id: target.id } })
}
function putDocument(post: Record<string, unknown>) {
	const target = props.target
	if(!target) return Promise.reject(new Error("Choose one first."))
	if(target.kind === "device") return api.put("/api/settings/{name}", { path: { name: target.name } }, post)
	if(target.kind === "plugin") return api.put("/api/plugins/{plugin_id}/settings", { path: { plugin_id: target.id } }, post)
	return api.put("/api/datasources/{datasource_id}/settings", { path: { datasource_id: target.id } }, post)
}
function send(post: any) {
	lastPost = post
	conflict.value = null
	putDocument(post)
	.then(jv => {
		if(jv.success) {
			_rev = jv.rev
			// what was saved is the new starting point: the form is no longer "changed" (leaving does not ask), and secrets show masked again
			fetchDocument().then(applySettings).catch(ex => console.warn("settings.reload", ex))
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
	fetchDocument()
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
			icon: "mi mi-warning",
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
/** The factory values, from the server's shipped copy; each goes in its field (nothing is saved until the user saves). */
async function factoryValues(): Promise<Record<string, unknown>|undefined> {
	try {
		const target = props.target
		if(target?.kind !== "device") return undefined
		// the shipped document's values (open: its keys are its schema's)
		return await api.get("/api/settings/{name}/defaults", { path: { name: target.name } }) as Record<string, unknown>
	}
	catch(ex) {
		emits("submit", { result: null, invalid: null, error: ex })
		return undefined
	}
}
const restoreField = async (name: string) => {
	const values = await factoryValues()
	if(values && name in values) bf.value?.setValue(name, values[name])
}
const restoreAll = async () => {
	const values = await factoryValues()
	if(values) Object.entries(values).forEach(([name, value]) => bf.value?.setValue(name, value))
}
// a field offers its own restore button only when the form has a source of factory values
provide("restoreField", props.defaults ? restoreField : null)
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