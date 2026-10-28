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
				<label id="auth-code-label">Setup code</label>
				<!-- the 8 digits, one box each (#731): typing moves on, a paste (even "1234 5678") fills them all -->
				<InputOtp v-model="code" :length="8" integerOnly size="small" class="auth-code" role="group" aria-labelledby="auth-code-label" @paste.capture="pasteCode">
					<template #default="{ attrs, events, index }">
						<InputText v-bind="attrs" v-on="events" size="small" class="p-inputotp-input" inputmode="numeric" autocomplete="off" :aria-label="`Setup code digit ${index}`" />
					</template>
				</InputOtp>
			</div>
			<div class="auth-field">
				<label for="auth-secret">{{ secretLabel }}</label>
				<InputText size="small" id="auth-secret" v-model="secret" type="password" fluid :autocomplete="authPrompt.mode === 'setup' ? 'new-password' : 'current-password'" :aria-label="secretLabel" />
			</div>
			<div v-if="authPrompt.mode === 'setup'" class="auth-field">
				<label for="auth-again">Repeat the password</label>
				<InputText size="small" id="auth-again" v-model="again" type="password" fluid autocomplete="new-password" aria-label="Repeat the password" />
			</div>
			<Message v-if="authPrompt.error" severity="error" size="small" variant="simple" role="alert">{{ authPrompt.error }}</Message>
			<div class="auth-buttons">
				<Button size="small" type="button" label="Cancel" severity="secondary" text :disabled="authPrompt.busy" @click="cancelAuth" />
				<Button size="small" type="submit" :label="submitLabel" :loading="authPrompt.busy" />
			</div>
		</form>
	</Dialog>
</template>
<script setup lang="ts">
/** The sign-in and first-run setup dialog (AuthPrompt.ts has the state; ApiClient.ts opens it on a 401). */
import { computed, ref, watch } from "vue"
import { Button, Dialog, InputOtp, InputText, Message } from "primevue"
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

/** The code is shown as "1234 5678": a paste of it (spaces and all) is the digits, which the component alone would refuse for the space. */
function pasteCode(event: ClipboardEvent) {
	const digits = (event.clipboardData?.getData("text") ?? "").replace(/\D/g, "")
	event.preventDefault()
	event.stopPropagation()
	if (digits) code.value = digits.slice(0, 8)
}
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
.auth-code { justify-content: space-between; }
.auth-buttons { display: flex; justify-content: flex-end; gap: .5rem; margin-top: .25rem; }
</style>
