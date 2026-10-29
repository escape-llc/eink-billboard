<template>
	<!-- one line of what the device did last (a problem from the last hour first), with how long ago; it opens the System page's Activity panel -->
	<RouterLink v-if="latest" class="latest" :class="{ problem: latest.problem }" data-testid="latest-activity" :data-problem="latest.problem"
		:to="{ name: 'system', query: { activity: latest.problem ? 'problems' : 'all' } }" :title="latest.problem ? 'Show the problems in Activity' : 'Show Activity'">
		<i :class="eventIcon(latest.event)" aria-hidden="true"></i>
		<span class="text">{{ describeEvent(latest.event) }}</span>
		<span class="ago" :title="clockOf(latest.event.ts)">· {{ relativeTime(latest.event.ts, now) }}</span>
	</RouterLink>
	<p v-else class="latest muted" data-testid="latest-activity">Nothing has happened yet.</p>
</template>
<script setup lang="ts">
/**
 * Home's activity line (#824): the latest thing the device did, or a problem from the last hour over it, with how long ago. A relative time goes
 * stale as it stands, so it is worked out again every `TICK_MS`.
 */
import { computed, onBeforeUnmount, ref } from "vue"
import { RouterLink } from "vue-router"
import { clockOf, useTelemetry } from "./TelemetryLink"
import { describeEvent, eventIcon, latestActivity, relativeTime } from "../composables/usePanelNow"

const TICK_MS = 30000
const link = useTelemetry()
const now = ref(Date.now())
const timer = setInterval(() => { now.value = Date.now() }, TICK_MS)
onBeforeUnmount(() => clearInterval(timer))
const latest = computed(() => latestActivity(link.state.events, now.value))
</script>
<style scoped>
.latest {
	display: flex;
	align-items: baseline;
	gap: .4rem;
	min-width: 0;
	margin: 0;
	padding: .5rem .75rem;
	border-radius: var(--p-toolbar-border-radius);
	border: solid 1px var(--p-toolbar-border-color);
	background: var(--p-content-background);
	color: inherit;
	text-decoration: none;
}
a.latest:hover .text {
	text-decoration: underline;
}
.latest.problem {
	color: var(--p-red-500);
}
.latest i {
	align-self: center;
}
.text {
	min-width: 0;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.ago {
	flex: none;
	color: var(--p-text-muted-color);
}
.problem .ago {
	color: inherit;
}
.muted {
	color: var(--p-text-muted-color);
}
</style>
