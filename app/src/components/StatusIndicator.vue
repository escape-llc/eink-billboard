<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Button, Popover } from 'primevue'
import { apiJson, joinUrl, signInCount } from './ApiClient'

type Component = { state: "ok" | "failed" | "starting", message: string }
type Status = { ok: boolean, components: Record<string, Component> }

const POLL_MS = 10000
const status = ref<Status | null>(null)
const popover = ref<InstanceType<typeof Popover> | null>(null)
let timer: ReturnType<typeof setInterval> | undefined

const TITLES: Record<string, string> = { "display": "Display", "playlist-layer": "Playlist", "timer-layer": "Timer tasks" }
const failed = computed(() => Object.values(status.value?.components ?? {}).some(c => c.state === "failed"))
const icon = computed(() => failed.value ? "pi pi-exclamation-triangle" : status.value?.ok ? "pi pi-check-circle" : "pi pi-spin pi-spinner")
const severity = computed(() => failed.value ? "danger" : status.value?.ok ? "success" : "secondary")
const label = computed(() => failed.value ? "A part of the device did not start" : status.value?.ok ? "The device is running" : "The device is starting")

const load = () => {
	apiJson<Status>(joinUrl(import.meta.env.VITE_API_URL ?? "/", "api/status")).then(s => { status.value = s }).catch(() => {})
}
onMounted(() => { load(); timer = setInterval(load, POLL_MS) })
onBeforeUnmount(() => { if (timer) clearInterval(timer) })
// it is outside the routed page that a sign-in builds again: read now, not at the next poll
watch(signInCount, load)
</script>
<template>
	<Button size="small"
		v-if="status"
		:icon="icon"
		:severity="severity"
		class="p-button-sm p-button-outlined"
		type="button"
		:aria-label="label"
		:title="label"
		data-testid="status"
		:data-state="failed ? 'failed' : status.ok ? 'ok' : 'starting'"
		@click="popover?.toggle($event)"
	/>
	<Popover ref="popover">
		<div v-if="status" class="flex flex-column gap-2" style="min-width:16rem">
			<div v-for="(c, name) in status.components" :key="name" class="flex flex-row gap-2 align-items-baseline">
				<span :class="c.state === 'failed' ? 'pi pi-times-circle' : c.state === 'ok' ? 'pi pi-check-circle' : 'pi pi-clock'" />
				<span><b>{{ TITLES[name] ?? name }}</b>: {{ c.message }}</span>
			</div>
		</div>
	</Popover>
</template>
