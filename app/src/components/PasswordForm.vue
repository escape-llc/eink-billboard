<template>
	<section class="password-form" data-testid="password-form">
		<h3>{{ info.passwordSet ? "Change the device password" : "Set a device password" }}</h3>
		<p v-if="!info.passwordSet" class="password-help">
			{{ info.localOnly ? "This device is open to this computer only. With a password, signing in is required here too." : "The device has an API token but no password." }}
		</p>
		<form class="password-fields" @submit.prevent="submit">
			<div v-if="info.passwordSet" class="password-field">
				<label for="pw-current">Current password</label>
				<InputText size="small" id="pw-current" v-model="current" type="password" autocomplete="current-password" aria-label="Current password" />
			</div>
			<div class="password-field">
				<label for="pw-new">New password</label>
				<InputText size="small" id="pw-new" v-model="next" type="password" autocomplete="new-password" aria-label="New password" />
			</div>
			<div class="password-field">
				<label for="pw-again">Repeat the new password</label>
				<InputText size="small" id="pw-again" v-model="again" type="password" autocomplete="new-password" aria-label="Repeat the new password" />
			</div>
			<Message v-if="problem" severity="error" size="small" variant="simple" role="alert">{{ problem }}</Message>
			<Message v-if="done" severity="success" size="small" variant="simple" role="status">{{ done }}</Message>
			<div><Button size="small" type="submit" :label="info.passwordSet ? 'Change password' : 'Set password'" :loading="busy" /></div>
		</form>
	</section>
</template>
<script setup lang="ts">
/** Set or change the device password (PUT /api/access/password). The server keeps the browser signed in. */
import { onMounted, ref } from "vue"
import { Button, InputText, Message } from "primevue"
import { ApiError, apiJson, apiPut, joinUrl } from "./ApiClient"
import { MIN_PASSWORD, type AccessInfo } from "./AuthPrompt"

const base = import.meta.env.VITE_API_URL ?? "/"
const ACCESS = joinUrl(base, "api/access")
const info = ref<AccessInfo>({ required: false, setupRequired: false, passwordSet: false, localOnly: true })
const current = ref("")
const next = ref("")
const again = ref("")
const problem = ref("")
const done = ref("")
const busy = ref(false)

async function load() {
	info.value = await apiJson<AccessInfo>(ACCESS)
}
onMounted(() => { load().catch(() => {}) })

async function submit() {
	problem.value = ""
	done.value = ""
	if (next.value.length < MIN_PASSWORD) {
		problem.value = `The password needs at least ${MIN_PASSWORD} characters.`
		return
	}
	if (next.value !== again.value) {
		problem.value = "The two passwords are not the same."
		return
	}
	busy.value = true
	try {
		await apiPut(joinUrl(ACCESS, "password"), { current: current.value, new: next.value })
		done.value = "The password was changed."
		current.value = next.value = again.value = ""
		await load()
	}
	catch (e) {
		problem.value = e instanceof ApiError ? e.message : "The password could not be changed."
	}
	finally {
		busy.value = false
	}
}
</script>
<style scoped>
.password-form { max-width: 28rem; }
.password-form h3 { margin: 0 0 .5rem 0; }
.password-help { margin: 0 0 .5rem 0; }
.password-fields { display: flex; flex-direction: column; gap: .75rem; }
.password-field { display: flex; flex-direction: column; gap: .25rem; }
</style>
