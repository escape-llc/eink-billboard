<template>
	<!-- what only a restart applies (useRestart): under the header on every page, with the way to do it -->
	<Message size="small" v-if="waiting.length > 0" severity="warn" :closable="false" class="restart-banner" data-testid="restart-banner">
		<div class="restart-row">
			<div>
				<p v-for="words in waiting" :key="words" class="m-0">{{ words }}</p>
				<p v-if="!available" class="m-0">Restart the app where it runs to apply it.</p>
			</div>
			<Button v-if="available" size="small" severity="danger" type="button" label="Restart" icon="mi mi-restart-alt" data-testid="restart-banner-button" @click="ask" />
		</div>
	</Message>
</template>
<script setup lang="ts">
import { Button, Message } from "primevue"
import { useRestart } from "../composables/useRestart"
import { useAskRestart } from "./AskRestart"

const { waiting, available } = useRestart()
const ask = useAskRestart()
</script>
<style scoped>
.restart-banner {
	margin: .25rem 0;
}
.restart-row {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 1rem;
}
</style>
