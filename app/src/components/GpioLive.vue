<template>
	<!-- the buttons as they are used, at two levels: what the pin did ("pin"), and what the device made of it ("action"); newest first. Press a button to see the wiring work -->
	<section class="gpio-live" aria-label="Buttons, live" data-testid="gpio-live">
		<h3 class="m-0">Buttons, live</h3>
		<ol class="event-list">
			<li v-for="(e, i) in shown" :key="e.seq ?? `x${i}`" class="event" :class="{ ignored: e.values?.result === 'ignored' }" :data-level="e.kind === 'gpio' ? 'pin' : 'action'">
				<span class="time">{{ clockOf(e.ts) }}</span>
				<Tag :value="e.kind === 'gpio' ? 'Pin' : 'Action'" :severity="e.kind === 'gpio' ? 'secondary' : e.values?.result === 'ignored' ? 'warn' : 'success'" />
				<span class="text">{{ describe(e) }}</span>
			</li>
			<li v-if="shown.length === 0" class="muted">Nothing yet: press a button.</li>
		</ol>
	</section>
</template>
<script setup lang="ts">
/**
 * The GPIO tab's live view of the buttons: the link's `gpio` events (a pin's own level: pressed, held, released, whatever it is set to) and `input` events (what the press became, or why
 * it became nothing). The page's one link is App.vue's.
 */
import { computed } from "vue"
import { Tag } from "primevue"
import { clockOf, useTelemetry } from "./TelemetryLink"
import { describeEvent as describe } from "../composables/usePanelNow"

const SHOWN = 8
const link = useTelemetry()
const shown = computed(() => link.state.events.filter(e => e.kind === "gpio" || e.kind === "input").slice(0, SHOWN))
</script>
<style scoped>
.gpio-live {
	display: flex;
	flex-direction: column;
	gap: .5rem;
	margin-top: 1rem;
	padding: .5rem .75rem;
	border-radius: var(--p-toolbar-border-radius);
	border: solid 1px var(--p-toolbar-border-color);
}
.event-list {
	display: flex;
	flex-direction: column;
	gap: .25rem;
	margin: 0;
	padding: 0;
	list-style: none;
}
.event {
	display: flex;
	align-items: center;
	gap: .5rem;
}
.time {
	color: var(--p-text-muted-color);
	font-variant-numeric: tabular-nums;
}
.muted {
	color: var(--p-text-muted-color);
}
</style>
