<template>
	<!-- the device's state on every page (useDeviceStatus): a link to the System page, which says more -->
	<RouterLink to="/system" class="device-status" :title="shown.title" :aria-label="`Device: ${shown.short}`" data-testid="device-status" :data-state="shown.state">
		<Tag :severity="shown.severity" :value="shown.short" />
	</RouterLink>
</template>
<script setup lang="ts">
import { Tag } from "primevue"
import { RouterLink } from "vue-router"
import { useDeviceStatus } from "../composables/useDeviceStatus"

const { shown } = useDeviceStatus()
</script>
<style scoped>
.device-status {
	display: inline-flex;
	align-items: center;
	text-decoration: none;
	flex: none;
}
</style>
