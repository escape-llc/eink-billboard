<template>
	<!-- `bare`: only the button, a member of an input group; the answer goes to the parent (`result`), which shows it with the rest of the field's feedback -->
	<Button v-if="bare" size="small" severity="secondary" icon="pi pi-bolt" label="Test" type="button" :loading="busy" :disabled="disabled || busy || !hasValue"
		:aria-label="`Test ${label}`" @click="run" />
	<div v-else class="test-url">
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
	/** only the button (joined to the input by the group it is in); the answer is sent as `result` */
	bare?: boolean
}
export type TestResult = { ok: boolean, message: string }
const props = withDefaults(defineProps<PropsType>(), { label: "value" })
const emits = defineEmits<{ (e: "result", value: TestResult | null): void }>()
const busy = ref(false)
const result = ref<TestResult | null>(null)
// the parent that shows the answer itself is told of every change of it
watch(result, value => emits("result", value))
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
