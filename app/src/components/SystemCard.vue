<template>
	<!-- a card of the System page: its heading opens and closes it, and a closed card shows its summary (a line of what the open card says) -->
	<section class="card" :aria-label="title" :data-open="open">
		<div class="card-head">
			<button type="button" class="toggle" :aria-expanded="open" :aria-controls="bodyId" @click="open = !open">
				<i class="mi mi-chevron-right chevron" aria-hidden="true"></i>
				<strong>{{ title }}</strong>
			</button>
			<slot name="head"></slot>
		</div>
		<div v-if="open" :id="bodyId" class="card-body"><slot></slot></div>
		<div v-else-if="$slots.summary" class="card-summary"><slot name="summary"></slot></div>
	</section>
</template>
<script setup lang="ts">
/**
 * A card of the System page that opens and closes (#520). Whether it starts open is the page's choice (`collapsed`), and it is not remembered: the browser stores
 * nothing but the theme.
 */
import { ref, useId } from "vue"

const props = withDefaults(defineProps<{ title: string, collapsed?: boolean }>(), { collapsed: false })
const open = ref(!props.collapsed)
const bodyId = useId()
</script>
<style scoped>
.card {
	display: flex;
	flex-direction: column;
	gap: .5rem;
	min-width: 0;
	padding: .5rem .75rem;
	border-radius: var(--p-toolbar-border-radius);
	border: solid 1px var(--p-toolbar-border-color);
	background: var(--p-content-background);
}
.card-head {
	display: flex;
	align-items: center;
	gap: .5rem;
}
.toggle {
	display: flex;
	align-items: center;
	gap: .35rem;
	padding: 0;
	border: none;
	background: none;
	color: inherit;
	font: inherit;
	cursor: pointer;
	text-align: left;
}
.chevron {
	color: var(--p-text-muted-color);
	transition: transform .15s;
}
.toggle[aria-expanded="true"] .chevron {
	transform: rotate(90deg);
}
.card-body {
	display: flex;
	flex-direction: column;
	gap: .5rem;
	min-width: 0;
}
.card-summary {
	color: var(--p-text-muted-color);
	font-size: .85rem;
}
</style>
