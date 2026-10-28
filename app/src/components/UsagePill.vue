<template>
	<!-- two tones: the label on the tone of what it means, the value beside it on a neutral one, so nothing needs a separator -->
	<!-- a glyph stands for the label where its meaning is plain (#796): the label is then the pill's name for a screen reader, and the title says it in words -->
	<span class="pill" :class="kind" role="listitem" :title="title" :aria-label="icon ? `${label} ${value}` : undefined" :data-testid="testid">
		<span class="pill-label"><i v-if="icon" :class="['mi', iconClass(icon)]" aria-hidden="true"></i><template v-else>{{ label }}</template></span><span class="pill-value">{{ value }}</span>
	</span>
</template>

<script setup lang="ts">
import { iconClass, type MaterialIconName } from "./MaterialIcons"
import type { PillKind } from "./SystemFormat"

defineProps<{ label: string, value: string | number, kind: PillKind, title?: string, icon?: MaterialIconName, testid?: string }>()
</script>

<style scoped>
.pill {
	display: inline-flex;
	overflow: hidden;
	border-radius: 999px;
	border: 1px solid var(--pill-tone);
	font-size: .75rem;
	line-height: 1.5;
	font-weight: 600;
	white-space: nowrap;
}
.pill-label {
	display: inline-flex;
	align-items: center;
	padding: 0 .5rem;
	background: var(--pill-tone);
	color: var(--pill-on);
}
.pill-label .mi {
	--mi-size: .9rem;
	vertical-align: 0;
}
.pill-value {
	padding: 0 .5rem;
	background: var(--p-content-background);
	color: var(--p-text-color);
	font-variant-numeric: tabular-nums;
}
.pill.neutral { --pill-tone: var(--p-content-border-color); --pill-on: var(--p-text-color); }
.pill.success { --pill-tone: var(--p-tag-success-background); --pill-on: var(--p-tag-success-color); }
.pill.info { --pill-tone: var(--p-tag-info-background); --pill-on: var(--p-tag-info-color); }
.pill.warn { --pill-tone: var(--p-tag-warn-background); --pill-on: var(--p-tag-warn-color); }
.pill.danger { --pill-tone: var(--p-tag-danger-background); --pill-on: var(--p-tag-danger-color); }
</style>
