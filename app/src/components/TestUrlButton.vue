<template>
	<div class="test-url">
		<Button size="small" severity="secondary" icon="pi pi-bolt" label="Test" type="button" :loading="busy" :disabled="disabled || busy || !hasValue"
			:aria-label="`Test ${label}`" @click="run" />
		<Message v-if="result" :severity="result.ok ? 'success' : 'error'" size="small" variant="simple">{{ result.message }}</Message>
	</div>
</template>
<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { Button, Message } from "primevue"
import { apiPost, joinUrl } from "./ApiClient"

export interface PropsType {
	/** the server's check for this field (`test.url` of the property): it gets `{ value }` and answers `{ ok, message }` */
	route: string
	baseUrl: string
	value: unknown
	/** what is being tested, for the button's accessible name */
	label?: string
	/** the value is not valid, so there is nothing to test yet */
	disabled?: boolean
}
const props = withDefaults(defineProps<PropsType>(), { label: "value" })
const busy = ref(false)
const result = ref<{ ok: boolean, message: string }|null>(null)
const hasValue = computed(() => typeof props.value === "string" && props.value !== "")
// an answer is about the value that was sent: a change makes it stale, and so does a newer request
let sent = 0
watch(() => props.value, () => { result.value = null; busy.value = false; sent++ })
async function run() {
	const mine = ++sent
	busy.value = true
	result.value = null
	try {
		const answer = await apiPost(joinUrl(props.baseUrl, props.route), { value: props.value })
		if (mine === sent) result.value = { ok: answer?.ok === true, message: String(answer?.message ?? "") }
	}
	catch (ex: any) {
		// the server's own message (never the address): the call itself failed
		if (mine === sent) result.value = { ok: false, message: ex?.message || "The test could not be run." }
	}
	finally {
		if (mine === sent) busy.value = false
	}
}
</script>
<style scoped>
.test-url {
	display: flex;
	flex-wrap: wrap;
	align-items: center;
	gap: .5rem;
	margin-top: .25rem;
}
</style>
