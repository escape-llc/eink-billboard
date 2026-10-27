<template>
	<!-- two tones: the label on the tone of what it means, the value beside it on a neutral one, so nothing needs a separator -->
	<span class="pill" :class="kind" role="listitem" :title="title">
		<span class="pill-label">{{ label }}</span><span class="pill-value">{{ value }}</span>
	</span>
</template>

<script setup lang="ts">
import type { PillKind } from "./SystemFormat"

defineProps<{ label: string, value: string | number, kind: PillKind, title?: string }>()
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
	padding: 0 .5rem;
	background: var(--pill-tone);
	color: var(--pill-on);
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
