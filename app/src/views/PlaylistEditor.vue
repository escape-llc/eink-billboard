<template>
	<div class="playlist-editor">
		<Toolbar class="p-1">
			<template #start>
				<div style="font-size:150%">Playlists</div>
			</template>
			<template #end>
				<!-- the playlist and what can be done to it, as one group -->
				<InputGroup class="playlist-actions">
					<Select :key="selectKey" :options="playlists" optionLabel="name" optionValue="id" :modelValue="currentId" placeholder="No playlist" size="small" class="playlist-select"
						aria-label="Playlist" @update:modelValue="(id: string) => guard(() => openPlaylist(id))" />
					<Button title="New playlist" aria-label="New playlist" icon="mi mi-playlist-add" size="small" severity="secondary" @click="guard(startNew)" />
					<Button title="Rename playlist" aria-label="Rename playlist" icon="mi mi-edit" size="small" severity="secondary" :disabled="!currentId" @click="startRename" />
					<Button title="Delete playlist" aria-label="Delete playlist" icon="mi mi-delete" size="small" severity="danger" :disabled="!currentId" @click="deleteOpen = true" />
					<Button title="Add Track" aria-label="Add track" icon="mi mi-add" size="small" :disabled="!currentId" @click="addTrack" />
					<Button title="Save playlist" aria-label="Save playlist" icon="mi mi-save" size="small" severity="success" :disabled="!currentId || !dirty || saving" @click="savePlaylist" />
				</InputGroup>
			</template>
		</Toolbar>
		<ProgressBar v-if="loading" mode="indeterminate" style="height:4px" aria-label="Loading" data-testid="loading" />
		<!-- nothing reaches the device until the playlist is saved: a warning in its own box, across the page, not a line of small print -->
		<Message v-if="dirty" severity="warn" size="small" icon="mi mi-warning" class="mt-1 unsaved-banner" data-testid="unsaved-banner" role="status">
			Unsaved changes to "{{ playlistName }}": save the playlist to keep them.
		</Message>
		<Message size="small" v-if="conflict" severity="warn" :closable="false" class="mt-1">
			<div class="flex align-items-center gap-2">
				<span>{{ conflict.message }}</span>
				<Button size="small" label="Reload" icon="mi mi-refresh" severity="secondary" @click="reloadPlaylist" />
				<Button v-if="conflict.rev" size="small" label="Overwrite" icon="mi mi-upload" severity="danger" @click="overwrite" />
			</div>
		</Message>
		<Message v-for="(problem, index) in serverProblems" :key="index" severity="error" size="small" variant="simple">{{ problem }}</Message>

		<div class="layout">
			<div class="track-list">
				<ul>
					<li v-for="(t, idx) in tracks" :key="t.id" :class="{ selected: selectedIndex === idx }">
						<div class="track-row" @click="selectTrack(idx)">
							<div class="track-meta">
								<div class="title">{{  t.title  }}</div>
								<div>{{ describeOf(t) }}</div>
							</div>
							<div class="actions">
								<Button icon="mi mi-arrow-upward" aria-label="Move up" size="small" class="p-button-text" :disabled="idx === 0" @click.stop="moveTrack(idx, -1)" />
								<Button icon="mi mi-arrow-downward" aria-label="Move down" size="small" class="p-button-text" :disabled="idx === tracks.length - 1" @click.stop="moveTrack(idx, 1)" />
								<Button icon="mi mi-delete" aria-label="Remove track" size="small" severity="danger" class="p-button-text"
									@click.stop="removeTrack(idx)" />
							</div>
						</div>
					</li>
					<!-- a new track is a draft until it is applied: shown where it will go, not part of the playlist (no unsaved change until then) -->
					<li v-if="draft" class="selected draft" data-testid="draft-track">
						<div class="track-row">
							<div class="track-meta">
								<div class="title">{{ editModel.title || "Untitled" }}</div>
								<div>New track: apply it to add it, or cancel</div>
							</div>
						</div>
					</li>
				</ul>
				<p v-if="currentId && tracks.length === 0 && !draft" class="m-1">No tracks yet.</p>
				<p v-if="!currentId" class="m-1">{{ playlists.length === 0 ? "This device has no playlist yet, so its panel has nothing to show. Create one (the + button above), add tracks, and save it." : "Choose or create a playlist to add tracks." }}</p>
			</div>

			<div class="track-editor">
				<div v-if="selectedTrack" class="editor-card">
					<BasicForm ref="bf" v-if="selectedPlugin" :baseUrl="API_URL" :form="selectedPlugin.instanceSettings" :owner="{ kind: 'plugin', id: selectedPlugin.id }" :initialValues="editModel.content" :showHelp="showHelp" :showChanges="true"
						@validate="handleValidate" @submit="submitForm">
						<template #header>
							<Toolbar style="width:100%" class="p-1 mt-2">
								<template #start>
									<div style="font-weight: bold;font-size:150%">Track Settings</div>
								</template>
								<template #end>
									<InputGroup>
										<HelpToggle v-model="showHelp" />
										<Button size="small" icon="mi mi-check" severity="success" aria-label="Apply track" title="Apply to the playlist (then save it)" :disabled="applyDisabled" @click="handleSubmit" />
										<Button size="small" icon="mi mi-close" severity="danger" aria-label="Reset track" @click="handleReset" />
									</InputGroup>
								</template>
							</Toolbar>
						</template>
						<template #group-header="slotProps">
							<h3 class="mb-0">{{ slotProps.title }}</h3>
						</template>
						<template #before-fields>
							<InputGroup class="field-row">
								<InputGroupAddon class="field-label">
									<label class="field-title" :style="{ '--label-width': fieldNameWidth }">Title</label>
								</InputGroupAddon>
								<InputText style="flex-grow:1" size="small" v-model="editModel.title" />
							</InputGroup>
							<InputGroup class="field-row">
								<InputGroupAddon class="field-label">
									<label class="field-title" :style="{ '--label-width': fieldNameWidth }">Plugin</label>
								</InputGroupAddon>
								<Select size="small" :options="pluginOptions" optionLabel="name" optionValue="id" v-model="editModel.plugin_name" />
							</InputGroup>
						</template>
					</BasicForm>
				</div>

				<div v-else class="empty-state">
					<p>Select a track to edit its properties.</p>
				</div>
			</div>
		</div>

		<Dialog v-model:visible="nameOpen" modal :header="nameDialogRename ? 'Rename playlist' : 'New playlist'" style="width:24rem;max-width:95vw">
			<InputText size="small" v-model="nameValue" aria-label="Playlist name" fluid autofocus @keyup.enter="confirmName" />
			<div class="flex gap-2 justify-content-end pt-2">
				<Button size="small" type="button" label="Cancel" severity="secondary" @click="nameOpen = false"></Button>
				<Button size="small" type="button" label="OK" :disabled="!nameValue.trim() || saving" @click="confirmName"></Button>
			</div>
		</Dialog>
		<Dialog v-model:visible="deleteOpen" modal header="Delete playlist?" style="width:24rem;max-width:95vw">
			<p class="mt-0">"{{ playlistName }}" and its tracks will be removed.</p>
			<div class="flex gap-2 justify-content-end">
				<Button size="small" type="button" label="Keep" severity="secondary" @click="deleteOpen = false"></Button>
				<Button size="small" type="button" label="Delete" severity="danger" :disabled="saving" @click="deletePlaylist"></Button>
			</div>
		</Dialog>
		<Dialog v-model:visible="discardOpen" modal header="Discard unsaved changes?" style="width:24rem;max-width:95vw" @hide="onDiscardHide">
			<p class="mt-0">The changes to "{{ playlistName }}" were not saved.</p>
			<div class="flex gap-2 justify-content-end">
				<Button size="small" type="button" label="Keep editing" severity="secondary" @click="discardOpen = false"></Button>
				<Button size="small" type="button" label="Discard" severity="danger" @click="confirmDiscard"></Button>
			</div>
		</Dialog>
	</div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, provide } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { InputGroup, InputGroupAddon, Toolbar, Button, Select, InputText, Dialog, Message, ProgressBar, useToast } from 'primevue'
import BasicForm, { type ValidateEventData } from '../components/BasicForm.vue'
import HelpToggle from '../components/HelpToggle.vue'
import { usePlaylists } from '../composables/usePlaylists'
const API_URL = import.meta.env.VITE_API_URL
const toast = useToast()
// the playlists, the working copy and the track in the editor, with every call that loads or saves them
const {
	plugins, dataSources, playlists, currentId, playlistName, tracks, dirty, saving, conflict, serverProblems, selectedIndex, draft, loading, editModel,
	selectedTrack, selectedPlugin, pluginOptions,
	describeOf, selectTrack, cancelEdit, applyEdit, addTrack, removeTrack, moveTrack,
	start, loadPlaylists, createPlaylist, renamePlaylist, deletePlaylist: removePlaylist, savePlaylist: save, overwritePlaylist, reloadPlaylist, discardChanges, stop,
} = usePlaylists((severity, detail) => toast.add(severity === "success"
	? { severity, summary: "Success", detail, life: 3000 }
	: { severity, summary: "Error", detail, life: 5000 }))
provide("settingsPluginsList", plugins)
provide("settingsDataSourcesList", dataSources)

const bf = ref<InstanceType<typeof BasicForm>>()
// the fields' help text; for this page's life only (the browser stores nothing but the theme)
const showHelp = ref(true)
const submitDisabled = ref(true)
const fieldNameWidth = "10rem";
const nameOpen = ref(false)
const nameDialogRename = ref(false)
const nameValue = ref("")
const deleteOpen = ref(false)
const discardOpen = ref(false)
let pendingAction: (() => void)|undefined = undefined
// the playlist select shows what was picked, even when the change is refused: a new key makes it show the playlist again
const selectKey = ref(0)

// Apply has nothing to apply until something changed: the title, the plugin or a field (a draft is new, so it can always be applied)
const applyDisabled = computed(() => {
	if(submitDisabled.value) return true
	if(draft.value) return false
	const track = selectedTrack.value
	if(!track) return true
	return track.title === editModel.title && track.plugin_name === editModel.plugin_name && !bf.value?.isDirty
})

const handleValidate = (e: ValidateEventData) => {
	submitDisabled.value = !e.result.success
}
/** Apply: the form's fields (only the selected plugin's) are the track's content. */
const submitForm = (data:any) => {
	if(!data.result?.success) return
	applyEdit(data.result.data)
}
const handleReset = () => {
	cancelEdit()
	bf.value?.reset()
}
const handleSubmit = () => {
	bf.value?.submit()
}
// a problem in a field of the track in the editor shows on that field
const onField = (errors: { path: unknown[], message: string }[]) => bf.value?.setServerErrors(errors) ?? 0
/** Save the playlist over the revision it was loaded at. */
const savePlaylist = () => save(onField)
/** In a conflict: save the working copy over what the server has now. */
const overwrite = () => overwritePlaylist(onField)

// --- the dialogs
async function openPlaylist(id: string) {
	await loadPlaylists(id)
}
/** Run an action that drops the working copy; ask first when it has changes that were not saved. */
function guard(action: () => void) {
	if(dirty.value) {
		pendingAction = action
		discardOpen.value = true
	}
	else {
		action()
	}
}
// leaving the page (another page of the app, or closing the tab) asks too
let leaveAnswer: ((leave: boolean) => void)|undefined = undefined
onBeforeRouteLeave(() => {
	if(!dirty.value) return true
	return new Promise<boolean>(resolve => {
		leaveAnswer = resolve
		guard(() => resolve(true))
	})
})
const warnBeforeClose = (e: BeforeUnloadEvent) => {
	if(dirty.value) e.preventDefault()
}
function onDiscardHide() {
	pendingAction = undefined
	leaveAnswer?.(false)
	leaveAnswer = undefined
	selectKey.value++
}
function confirmDiscard() {
	const action = pendingAction
	pendingAction = undefined
	leaveAnswer = undefined
	discardOpen.value = false
	discardChanges()
	action?.()
}
function startNew() {
	nameDialogRename.value = false
	nameValue.value = ""
	nameOpen.value = true
}
function startRename() {
	nameDialogRename.value = true
	nameValue.value = playlistName.value ?? ""
	nameOpen.value = true
}
async function confirmName() {
	const name = nameValue.value.trim()
	if(!name) return
	const outcome = nameDialogRename.value && currentId.value ? await renamePlaylist(name) : await createPlaylist(name)
	// a conflict is shown on the page; a failure keeps the dialog open to try again
	if(outcome !== "failed") nameOpen.value = false
}
async function deletePlaylist() {
	await removePlaylist()
	deleteOpen.value = false
}
onMounted(() => {
	window.addEventListener("beforeunload", warnBeforeClose)
	start()
})
onBeforeUnmount(() => {
	window.removeEventListener("beforeunload", warnBeforeClose)
	stop()
})
</script>
<style scoped>
.unsaved-banner :deep(.p-message-content) {
	justify-content: center;
	font-weight: 600;
}
.label-panel {
	width: 20rem;
}
/* the page area is the window under the toolbar: the track list and the track's form each scroll inside it, and the page itself does not */
.playlist-editor {
	padding: 0.5rem;
	display: flex;
	flex-direction: column;
	overflow: hidden;
}

.layout {
	display: flex;
	gap: .5rem;
	margin-top: 0.5rem;
	flex: 1 1 0;
	min-height: 0;
}

.track-list {
	width: 25rem;
	border: 1px solid var(--p-content-border-color);
	border-radius: 4px;
	padding: 0.5rem;
	background: var(--p-content-background);
	flex: none;
	overflow: auto;
}

.track-list ul {
	list-style: none;
	padding: 0;
	margin: 0;
}

.track-row {
	display: flex;
	align-items: center;
	gap: 0.5rem;
	padding: 0.4rem;
	border-radius: 4px;
	cursor: pointer;
}

.track-row:hover {
	background: var(--p-content-hover-background);
}

.track-row.selected {
	background: var(--p-highlight-background);
	color: var(--p-highlight-color);
}

.color-swatch {
	width: 28px;
	height: 28px;
	border-radius: 4px;
	border: 1px solid var(--p-content-border-color);
}

.track-meta {
	flex: 1;
	display: flex;
	flex-direction: column;
}

.title {
	font-weight: 600;
}

.muted {
	color: var(--p-text-muted-color);
	font-size: 0.85rem;
}

.actions {
	display: flex;
	gap: 0.25rem;
}
.selected {
	background: var(--p-highlight-background);
	border: 1px solid var(--p-content-border-color);
}
/* a new track not applied yet: where it will go, dashed and muted, since it is not part of the playlist */
.draft {
	border-style: dashed;
	color: var(--p-text-muted-color);
	font-style: italic;
}
.track-editor {
	flex: 1;
	border: 1px solid var(--p-content-border-color);
	border-radius: 4px;
	padding: 0.75rem;
	min-height: 0;
	min-width: 0;
	overflow: auto;
	background: var(--p-content-background);
}

.editor-card {
	display: flex;
	flex-direction: column;
	gap: 0.6rem;
}

.field {
	display: flex;
	flex-direction: column;
	gap: 0.25rem;
}

.editor-actions {
	display: flex;
	gap: 0.5rem;
	justify-content: flex-end;
	margin-top: 0.5rem;
}

.empty-state {
	color: var(--p-text-muted-color);
	display: flex;
	align-items: center;
	justify-content: center;
	height: 100%;
}
.playlist-select {
	min-width: 14rem;
}
/* on a phone there is no room for two columns: the track list above the track's form, and the page area scrolls as one */
@media (max-width: 40rem) {
	.playlist-editor {
		overflow: visible;
	}
	.layout {
		flex-direction: column;
		flex: none;
	}
	.track-list {
		width: auto;
	}
	.track-editor {
		overflow: visible;
	}
	.playlist-select {
		min-width: 0;
		flex: 1 1 0;
	}
}
</style>