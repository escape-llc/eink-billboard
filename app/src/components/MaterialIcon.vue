<template>
	<!-- the SVG is one of our own files (MaterialIcons.ts), never user text: v-html is safe here -->
	<span class="material-icon" :role="label ? 'img' : undefined" :aria-label="label" :aria-hidden="label ? undefined : true" v-html="svg"></span>
</template>
<script setup lang="ts">
import { computed } from "vue"
import { MATERIAL_ICONS, type MaterialIconName } from "./MaterialIcons"

/** A Material Symbols glyph, 1em square in the text color. Without a `label` it is decoration (hidden from screen readers). */
const props = defineProps<{ name: MaterialIconName; label?: string }>()
const svg = computed(() => MATERIAL_ICONS[props.name])
</script>
<style scoped>
.material-icon {
	display: inline-flex;
	width: 1em;
	height: 1em;
	vertical-align: -.125em;
}
.material-icon :deep(svg) {
	width: 100%;
	height: 100%;
	fill: currentColor;
}
</style>
