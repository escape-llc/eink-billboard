<template>
	<section class="backup" data-testid="backup">
		<p v-if="part === 'backup'" class="backup-help">
			A backup is one file with all of this device's settings, including the API keys, so it is locked with a passphrase of its own (not the device password) that is not kept anywhere:
			without it the file cannot be opened. The device password is never in it.
		</p>

		<form v-if="part === 'backup'" class="backup-fields" data-testid="backup-make" @submit.prevent="makeBackup">
			<div class="backup-field">
				<label for="bk-pass">Passphrase (at least {{ MIN_PASSPHRASE }} characters)</label>
				<InputText size="small" id="bk-pass" v-model="passphrase" type="password" autocomplete="new-password" aria-label="Backup passphrase" />
			</div>
			<div class="backup-field">
				<label for="bk-again">Repeat the passphrase</label>
				<InputText size="small" id="bk-again" v-model="again" type="password" autocomplete="new-password" aria-label="Repeat the backup passphrase" />
			</div>
			<Message v-if="backupProblem" severity="error" size="small" variant="simple" role="alert">{{ backupProblem }}</Message>
			<Message v-if="backupDone" severity="success" size="small" variant="simple" role="status">{{ backupDone }}</Message>
			<div><Button size="small" type="submit" label="Download backup" icon="mi mi-download" :loading="backingUp" /></div>
		</form>

		<form v-if="part === 'restore'" class="backup-fields" data-testid="backup-restore" @submit.prevent="check">
			<div class="backup-field">
				<label>Backup file</label>
				<div class="backup-file">
					<Button size="small" type="button" label="Choose file" icon="mi mi-upload" severity="secondary" @click="chooser?.click()" />
					<span data-testid="backup-file-name">{{ file ? file.name : "No file chosen" }}</span>
				</div>
				<input ref="chooser" type="file" hidden aria-label="Backup file" data-testid="backup-file" @change="chosen" />
			</div>
			<div class="backup-field">
				<label for="rs-pass">Passphrase of the backup</label>
				<InputText size="small" id="rs-pass" v-model="restorePassphrase" type="password" autocomplete="off" aria-label="Passphrase of the backup" />
			</div>
			<Message v-if="restoreProblem" severity="error" size="small" variant="simple" role="alert">{{ restoreProblem }}</Message>
			<div v-if="!summary"><Button size="small" type="submit" label="Check backup" :loading="checking" :disabled="!file" /></div>
		</form>

		<div v-if="part === 'restore' && summary" class="backup-summary" data-testid="backup-summary">
			<p v-if="summary.files.length === 0">Nothing would change: this device already has everything in the backup.</p>
			<template v-else>
				<p>Restoring will write {{ summary.files.length }} {{ summary.files.length === 1 ? "file" : "files" }} ({{ summary.unchanged }} already the same):</p>
				<ul>
					<li v-for="f in summary.files" :key="f.name"><strong>{{ f.label }}</strong> ({{ f.status }})</li>
				</ul>
			</template>
			<p v-if="summary.madeAt" data-testid="backup-made">This backup was made {{ new Date(summary.madeAt).toLocaleString() }}.</p>
			<p v-if="summary.upgraded.length > 0" data-testid="backup-upgraded">{{ summary.upgraded.length }} {{ summary.upgraded.length === 1 ? "file comes" : "files come" }} from an older version and {{ summary.upgraded.length === 1 ? "is" : "are" }} brought up to date as {{ summary.upgraded.length === 1 ? "it is" : "they are" }} restored.</p>
			<p v-if="summary.leftOut > 0">{{ summary.leftOut }} {{ summary.leftOut === 1 ? "file" : "files" }} in the backup cannot be restored on this device and will be left out.</p>
			<p v-if="summary.restartNeeded">The display settings change only when the device starts again.</p>
			<p>Nothing is deleted: files this device has that the backup does not stay as they are.</p>
			<div class="backup-actions">
				<Button size="small" type="button" label="Restore" icon="mi mi-history" severity="danger" :loading="restoring" :disabled="summary.files.length === 0" data-testid="backup-apply" @click="apply" />
				<Button size="small" type="button" label="Cancel" severity="secondary" :disabled="restoring" @click="reset" />
			</div>
		</div>
		<Message v-if="part === 'restore' && restoreDone" severity="success" size="small" variant="simple" role="status">{{ restoreDone }}</Message>
	</section>
</template>
<script setup lang="ts">
/**
 * Back up the storage (one `part` at a time: the System page opens each in a dialog) to an encrypted file and restore it (POST /api/backup, POST /api/restore). The passphrase is typed here and sent in the request body only; it is
 * not kept (no storage of any kind) and the fields are cleared when it has been used. A restore is two steps: check (what would change, by name) and then restore.
 */
import { ref } from "vue"
import { Button, InputText, Message } from "primevue"
import { ApiError, apiDownload, joinUrl } from "./ApiClient"
import { api } from "../api/client"
import type { components } from "../api/schema"

defineProps<{ part: "backup" | "restore" }>()

const MIN_PASSPHRASE = 12
const base = import.meta.env.VITE_API_URL ?? "/"
const BACKUP = joinUrl(base, "api/backup")

type Summary = components["schemas"]["RestoreSummary"]

const passphrase = ref("")
const again = ref("")
const backupProblem = ref("")
const backupDone = ref("")
const backingUp = ref(false)

const chooser = ref<HTMLInputElement | null>(null)
const file = ref<File | null>(null)
const restorePassphrase = ref("")
const restoreProblem = ref("")
const restoreDone = ref("")
const summary = ref<Summary | null>(null)
const checking = ref(false)
const restoring = ref(false)

/** What the server said was wrong, in its words: the message, and the first few documents it names (never a value). */
function explain(e: unknown, fallback: string): string {
	if(!(e instanceof ApiError)) {
		return fallback
	}
	const named: string[] = (e.body?.errors ?? []).slice(0, 3).map((x: { path: string[], message: string }) => `${x.path.join(" / ")}: ${x.message}`)
	return named.length > 0 ? `${e.message} ${named.join("; ")}` : e.message
}

async function makeBackup() {
	backupProblem.value = ""
	backupDone.value = ""
	if(passphrase.value.length < MIN_PASSPHRASE) {
		backupProblem.value = `The passphrase needs at least ${MIN_PASSPHRASE} characters.`
		return
	}
	if(passphrase.value !== again.value) {
		backupProblem.value = "The two passphrases are not the same."
		return
	}
	backingUp.value = true
	try {
		const { blob, filename } = await apiDownload(BACKUP, { passphrase: passphrase.value, confirm: again.value })
		const url = URL.createObjectURL(blob)
		const link = document.createElement("a")
		link.href = url
		link.download = filename
		link.click()
		URL.revokeObjectURL(url)
		backupDone.value = `The backup was downloaded as ${filename}. Keep the passphrase: without it the file cannot be opened.`
		passphrase.value = again.value = ""
	}
	catch (e) {
		backupProblem.value = explain(e, "The backup could not be made.")
	}
	finally {
		backingUp.value = false
	}
}

function chosen(event: Event) {
	file.value = (event.target as HTMLInputElement).files?.[0] ?? null
	summary.value = null
	restoreDone.value = ""
	restoreProblem.value = ""
}

/** The file as base64, in pieces (one call with a spread of a few megabytes would overflow the stack). */
async function encoded(chosenFile: File): Promise<string> {
	const bytes = new Uint8Array(await chosenFile.arrayBuffer())
	let text = ""
	for(let at = 0; at < bytes.length; at += 0x8000) {
		text += String.fromCharCode(...bytes.subarray(at, at + 0x8000))
	}
	return btoa(text)
}

async function send(applyIt: boolean) {
	if(!file.value) {
		return null
	}
	return await api.post("/api/restore", {}, { archive: await encoded(file.value), passphrase: restorePassphrase.value, apply: applyIt })
}

async function check() {
	restoreProblem.value = ""
	restoreDone.value = ""
	if(!file.value || !restorePassphrase.value) {
		restoreProblem.value = "Choose the backup file and enter its passphrase."
		return
	}
	checking.value = true
	try {
		summary.value = await send(false)
	}
	catch (e) {
		restoreProblem.value = explain(e, "The backup could not be opened.")
	}
	finally {
		checking.value = false
	}
}

async function apply() {
	restoreProblem.value = ""
	restoring.value = true
	try {
		const done = await send(true)
		restoreDone.value = `The backup was restored: ${done?.written ?? 0} ${done?.written === 1 ? "file" : "files"} written.${done?.restartNeeded ? " Restart the device to apply the display settings." : ""}`
		reset()
	}
	catch (e) {
		restoreProblem.value = explain(e, "The backup could not be restored.")
	}
	finally {
		restoring.value = false
	}
}

function reset() {
	summary.value = null
	file.value = null
	restorePassphrase.value = ""
	if(chooser.value) {
		chooser.value.value = ""
	}
}
</script>
<style scoped>
.backup { max-width: 34rem; }
.backup-help { margin: 0 0 .75rem 0; }
.backup-fields { display: flex; flex-direction: column; gap: .75rem; }
.backup-field { display: flex; flex-direction: column; gap: .25rem; }
.backup-file { display: flex; align-items: center; gap: .75rem; }
.backup-summary ul { margin: .25rem 0 .75rem 0; padding-left: 1.25rem; }
.backup-actions { display: flex; gap: .5rem; }
</style>
