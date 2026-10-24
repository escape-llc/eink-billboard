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
						<Button size="small" icon="mi mi-check" severity="success" :disabled="!editor.canSave.value" @click="submit" />
						<Button size="small" icon="mi mi-close" severity="danger" @click="reset" />
					</InputGroup>
				</template>
			</Toolbar>
			<Message size="small" v-if="editor.inConflict.value" severity="warn" :closable="false" class="mt-1">
				<div class="flex align-items-center gap-2 flex-wrap">
					<span>{{ conflictMessage }}</span>
					<Button size="small" label="Reload" icon="mi mi-refresh" severity="secondary" @click="reload" />
					<Button size="small" label="Overwrite" icon="mi mi-upload" severity="danger" :disabled="!editor.canKeep.value" @click="overwrite" />
				</div>
			</Message>
			<slot name="header-end"></slot>
		</template>
	</BasicForm>
</template>
<script setup lang="ts">
import { ApiError } from "./ApiClient"
import { api } from "../api/client"
import { ref, watch, nextTick, onMounted, onBeforeUnmount, provide, toRaw } from "vue"
import { useEditor } from "../composables/useEditor"
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
// the editor's cycle (useEditor): the form reports its values, the editor decides what is unsaved, saves, and resolves a conflict
const editor = useEditor<Record<string, unknown>>({
	/** the stored document again (a discard, or taking theirs in a conflict); when it cannot be read, the page's copy */
	load: async () => {
		try {
			const doc: any = await fetchDocument()
			return { rev: doc._rev, show: () => showDocument(doc) }
		}
		catch(ex) {
			emits("submit", { result: null, invalid: null, error: ex })
			// a copy: the form starts again only for a new document
			const copy = props.settings ? structuredClone(toRaw(props.settings)) : undefined
			return { rev: copy?._rev, show: () => { if(copy) showDocument(copy) } }
		}
	},
	save: async (post, rev) => {
		const jv = await putDocument(rev ? { ...post, _rev: rev } : post)
		return jv.rev
	},
})
const conflictMessage = ref("")
let lastPost: Record<string, unknown>|undefined = undefined
let _id:string|undefined = undefined
let _schema:string|undefined = undefined

watch(() => props.settings, (nv) => {
	if(nv) {
		_id = nv._id
		_schema = nv._schema
		editor.loaded(nv._rev)
		nextTick().then(_ => {
			initialValues.value = nv
			emits("load-settings", nv)
		})
	}
	else {
		_id = undefined
		_schema = undefined
		editor.unload()
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
	editor.values(ved.values, ved.result.success)
	emits("validate", ved)
}
/** Show a document the form did not get from its page (after a save, a discard, a conflict); the editor's load or `loaded` says so to the machine. */
function showDocument(nv: any) {
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
async function send(post: Record<string, unknown>) {
	lastPost = post
	const { outcome, error } = await editor.save(post)
	if(outcome === "saved") {
		// what was saved is the new starting point: the form is no longer "changed" (leaving does not ask), and secrets show masked again
		fetchDocument().then((doc: any) => { editor.loaded(doc._rev); showDocument(doc) }).catch(ex => console.warn("settings.reload", ex))
		emits("submit", { result: { success: true, rev: editor.rev.value }, invalid: null, error: null })
	}
	else if(outcome === "conflict") {
		// somebody else saved first: let the user choose between their copy and ours
		conflictMessage.value = error instanceof Error ? error.message : "The settings changed since they were loaded."
		emits("submit", { result: null, invalid: null, error, handled: true })
	}
	else if(outcome === "failed") {
		if(error instanceof ApiError && error.status === 422 && Array.isArray(error.body?.errors)) {
			// each problem goes on its field
			bf.value?.setServerErrors(error.body.errors)
		}
		else {
			console.error("submitForm.unhandled", error)
		}
		emits("submit", { result: null, invalid: null, error })
	}
}
/** Drop the edits and show what the server has now. */
const reload = () => editor.takeTheirs()
/** Save the edits over what the server has now. */
const overwrite = () => {
	if(lastPost && editor.keep()) send(lastPost)
}
const confirm = useConfirm()
const leaving = (): boolean|Promise<boolean> => {
	if(!editor.hasUnsaved.value) return true
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
	if(editor.hasUnsaved.value) {
		e.preventDefault()
	}
}
onMounted(() => window.addEventListener("beforeunload", warnBeforeClose))
onBeforeUnmount(() => {
	window.removeEventListener("beforeunload", warnBeforeClose)
	editor.stop()
})
const submitForm = (data:any) => {
	if(data.data.valid) {
		// result.data has only the validated fields
		// the revision is the editor's to add (useEditor's save)
		const post = structuredClone(data.result.data)
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
/** Drop the edits: the stored document again (a form that only resets cannot tell that it is back where it started). */
const reset = async () => {
	if(!(await editor.discard())) bf.value?.reset()
	emits("reset", null)
}
const submit = () => {
	bf.value?.submit()
}
defineExpose({ submit, reset })
</script>
<style scoped>
</style>