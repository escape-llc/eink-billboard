<template>
	<!-- the device's state on every page (useDeviceStatus): a link to the System page, which says more. The first member of the header's group, joined to its buttons -->
	<InputGroupAddon class="device-status" :class="shown.severity">
		<RouterLink to="/system" :title="shown.title" :aria-label="`Device: ${shown.short}`" data-testid="device-status" :data-state="shown.state">{{ shown.short }}</RouterLink>
	</InputGroupAddon>
</template>
<script setup lang="ts">
import { InputGroupAddon } from "primevue"
import { RouterLink } from "vue-router"
import { useDeviceStatus } from "../composables/useDeviceStatus"

const { shown } = useDeviceStatus()
</script>
<style scoped>
/* the tone of a tag of that severity, on the addon itself: the group draws one box, so the state reads as part of the toolbar */
.device-status {
	padding: 0;
	font-size: .875rem;
	font-weight: 700;
	background: var(--tone-bg);
	color: var(--tone-fg);
}
.device-status a {
	display: inline-flex;
	align-items: center;
	align-self: stretch;
	padding: 0 .65rem;
	color: inherit;
	text-decoration: none;
}
.device-status.success { --tone-bg: var(--p-tag-success-background); --tone-fg: var(--p-tag-success-color); }
.device-status.info { --tone-bg: var(--p-tag-info-background); --tone-fg: var(--p-tag-info-color); }
.device-status.warn { --tone-bg: var(--p-tag-warn-background); --tone-fg: var(--p-tag-warn-color); }
.device-status.danger { --tone-bg: var(--p-tag-danger-background); --tone-fg: var(--p-tag-danger-color); }
.device-status.secondary { --tone-bg: var(--p-tag-secondary-background); --tone-fg: var(--p-tag-secondary-color); }
</style>
