<template>
	<!-- the app is gone while it restarts: nothing the page asks is answered, so the page waits here and loads again when it answers -->
	<Dialog :visible="restarting" modal :closable="false" header="Restarting" :style="{ width: '24rem' }" data-testid="restart-overlay">
		<div class="restart-wait">
			<ProgressSpinner style="width:2rem;height:2rem" strokeWidth="6" />
			<span>Restarting the app. This page loads again when it is back.</span>
		</div>
	</Dialog>
	<Message v-if="restartFailed" severity="error" class="restart-failed" data-testid="restart-failed">{{ restartFailed }}</Message>
</template>
<script setup lang="ts">
import { Dialog, Message, ProgressSpinner } from "primevue"
import { restarting, restartFailed } from "../composables/useRestart"
</script>
<style scoped>
.restart-wait {
	display: flex;
	align-items: center;
	gap: 1rem;
}
.restart-failed {
	margin: .25rem 0;
}
</style>
