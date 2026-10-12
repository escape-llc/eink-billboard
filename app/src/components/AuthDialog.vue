<template>
	<Dialog
		:visible="authPrompt.open"
		modal
		:header="title"
		:closable="!authPrompt.busy"
		style="width:26rem;max-width:95vw"
		@update:visible="onVisible"
	>
		<form class="auth-form" data-testid="auth-dialog" @submit.prevent="submit">
			<p class="auth-help">{{ help }}</p>
			<div v-if="authPrompt.mode === 'setup'" class="auth-field">
				<label for="auth-code">Setup code</label>
				<InputText id="auth-code" v-model="code" fluid autocomplete="off" inputmode="numeric" placeholder="1234 5678" aria-label="Setup code" />
			</div>
			<div class="auth-field">
				<label for="auth-secret">{{ secretLabel }}</label>
				<InputText id="auth-secret" v-model="secret" type="password" fluid :autocomplete="authPrompt.mode === 'setup' ? 'new-password' : 'current-password'" :aria-label="secretLabel" />
			</div>
			<div v-if="authPrompt.mode === 'setup'" class="auth-field">
				<label for="auth-again">Repeat the password</label>
				<InputText id="auth-again" v-model="again" type="password" fluid autocomplete="new-password" aria-label="Repeat the password" />
			</div>
			<Message v-if="authPrompt.error" severity="error" size="small" variant="simple" role="alert">{{ authPrompt.error }}</Message>
			<div class="auth-buttons">
				<Button type="button" label="Cancel" severity="secondary" text :disabled="authPrompt.busy" @click="cancelAuth" />
				<Button type="submit" :label="submitLabel" :loading="authPrompt.busy" />
			</div>
		</form>
	</Dialog>
</template>
<script setup lang="ts">
/** The sign-in and first-run setup dialog (AuthPrompt.ts has the state; ApiClient.ts opens it on a 401). */
import { computed, ref, watch } from "vue"
import { Button, Dialog, InputText, Message } from "primevue"
import { authPrompt, cancelAuth, submitAuth } from "./AuthPrompt"

const secret = ref("")
const again = ref("")
const code = ref("")

// each time it opens it starts empty: nothing typed is kept
watch(() => authPrompt.open, open => { if (open) { secret.value = ""; again.value = ""; code.value = "" } })

const title = computed(() => authPrompt.mode === "setup" ? "Set up this device" : "Sign in")
const secretLabel = computed(() => authPrompt.mode === "setup" ? "New password" : authPrompt.mode === "token" ? "API token" : "Password")
const submitLabel = computed(() => authPrompt.mode === "setup" ? "Set password" : "Sign in")
const help = computed(() => ({
	setup: "This device has not been set up. Enter the setup code shown on its e-Ink panel (or in its log), then choose a password.",
	password: "Enter the password of this device.",
	token: "This device requires an API token.",
})[authPrompt.mode])

function submit() {
	void submitAuth({ secret: secret.value, code: code.value, again: again.value })
}
function onVisible(visible: boolean) {
	if (!visible) cancelAuth()
}
</script>
<style scoped>
.auth-form { display: flex; flex-direction: column; gap: .75rem; }
.auth-help { margin: 0; }
.auth-field { display: flex; flex-direction: column; gap: .25rem; }
.auth-buttons { display: flex; justify-content: flex-end; gap: .5rem; margin-top: .25rem; }
</style>
