<template>
	<div class="row-action">
		<Button size="small" severity="secondary" icon="mi mi-link" type="button" :label="action.label" :loading="busy" :disabled="busy || !rowKey"
			:aria-label="`${action.label} ${label}`" @click="begin" />
		<div v-if="step" class="row-action-step" role="status">
			<div>{{ step.message }}</div>
			<a v-if="step.link" :href="step.link" target="_blank" rel="noopener noreferrer">{{ linkText }}</a>
			<code v-if="step.code" class="row-action-code" :aria-label="`Code for ${label}`">{{ step.code }}</code>
			<div v-if="step.input" class="row-action-input">
				<InputText size="small" fluid v-model="typed" :placeholder="step.input" :aria-label="`${step.input} for ${label}`" />
				<Button size="small" label="Continue" type="button" :disabled="!typed || busy" :aria-label="`Continue ${label}`" @click="send" />
			</div>
		</div>
		<Message v-if="result" :severity="result.ok ? 'success' : 'error'" size="small" variant="simple">{{ result.message }}</Message>
	</div>
</template>
<script setup lang="ts">
/** The steps of a row action (`items.action` of a list, see FormDefs.ts): start, then continue with typed text or poll, until done. */
import { computed, onBeforeUnmount, ref } from "vue"
import { Button, InputText, Message } from "primevue"
import { apiPost, joinUrl } from "./ApiClient"
import type { RowActionDef } from "./FormDefs"

const props = defineProps<{ action: RowActionDef, baseUrl: string, rowKey: unknown, label: string }>()
type Answer = { done?: boolean, ok?: boolean, message?: string, session?: string, link?: string, code?: string, input?: string, poll?: number }
const busy = ref(false)
const step = ref<Answer|null>(null)
const result = ref<{ ok: boolean, message: string }|null>(null)
const typed = ref("")
let session: string|undefined
let timer: ReturnType<typeof setTimeout>|undefined
// a newer start makes the answers of the older one stale
let run = 0

const linkText = computed(() => {
	try { return new URL(step.value?.link ?? "").host || "Open" } catch { return "Open" }
})
const url = (part: string) => joinUrl(props.baseUrl, `${props.action.url}/${part}`)
function stop() {
	if (timer) clearTimeout(timer)
	timer = undefined
}
onBeforeUnmount(stop)

function show(mine: number, answer: Answer) {
	if (mine !== run) return
	if (answer.done) {
		stop()
		step.value = null
		session = undefined
		result.value = { ok: answer.ok === true, message: String(answer.message ?? "") }
		return
	}
	if (answer.session) session = answer.session
	if (answer.message || answer.link || answer.code || answer.input) step.value = { ...step.value, ...answer }
	if (answer.poll) {
		stop()
		timer = setTimeout(() => call(mine, "poll", { session }), Math.max(1, answer.poll) * 1000)
	}
}
async function call(mine: number, part: string, body: unknown) {
	busy.value = part !== "poll"
	try {
		show(mine, await apiPost<Answer>(url(part), body))
	}
	catch (ex: any) {
		show(mine, { done: true, ok: false, message: ex?.message || "The step could not be run." })
	}
	finally {
		if (mine === run) busy.value = false
	}
}
function begin() {
	stop()
	const mine = ++run
	step.value = null
	result.value = null
	typed.value = ""
	call(mine, "start", { key: props.rowKey })
}
function send() {
	call(run, "continue", { session, value: typed.value })
}
</script>
<style scoped>
.row-action {
	display: flex;
	flex-direction: column;
	gap: .35rem;
	width: 100%;
}
.row-action-step {
	display: flex;
	flex-direction: column;
	gap: .35rem;
	padding: .5rem;
	border: 1px dashed var(--p-content-border-color);
	border-radius: var(--p-content-border-radius);
}
.row-action-code {
	font-size: 1.4rem;
	letter-spacing: .28rem;
	font-weight: bold;
}
.row-action-input {
	display: flex;
	gap: .5rem;
}
</style>
