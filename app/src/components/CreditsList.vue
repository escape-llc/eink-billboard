<template>
	<div class="credits" data-testid="credits">
		<p class="intro">eInk Billboard shows data, pictures and type made by others. This is everyone it owes, in one place, and the project that inspired it. The Weather pages and the maps also say it on the panel, as those services ask.</p>
		<Message v-if="failed" severity="error" size="small">The credits could not be loaded.</Message>
		<template v-if="credits">
			<section>
				<h4>Data and pictures</h4>
				<p class="hint">What the providers and data sources download. Calendars, feeds and pictures at your own addresses are yours.</p>
				<dl>
					<template v-for="d in credits.data" :key="d.id">
						<dt>{{ d.name }} <span class="kind">{{ d.provider ? "provider" : "data source" }}</span></dt>
						<dd>
							<a v-if="d.url" :href="d.url" target="_blank" rel="noopener noreferrer">{{ d.text }}</a><span v-else>{{ d.text }}</span>
							<span v-if="d.license" class="license">{{ d.license }}</span>
						</dd>
					</template>
				</dl>
			</section>
			<section>
				<h4>Fonts</h4>
				<p class="hint">Each shipped unmodified, under the SIL Open Font License 1.1, with its licence beside it.</p>
				<dl>
					<template v-for="f in credits.fonts" :key="f.name">
						<dt>{{ f.name }}</dt>
						<dd>{{ f.by }}</dd>
					</template>
				</dl>
			</section>
			<section>
				<h4>Software</h4>
				<dl>
					<template v-for="s in credits.software" :key="s.name">
						<dt>{{ s.name }}</dt>
						<dd>
							<span v-if="s.what">{{ s.what }}. </span>
							<a v-if="s.url" :href="s.url" target="_blank" rel="noopener noreferrer">{{ s.by }}</a><span v-else>{{ s.by }}</span>
							<span class="license">{{ s.license }}</span>
						</dd>
					</template>
				</dl>
			</section>
			<section v-for="part in [{ title: 'Artwork', items: credits.artwork }, { title: 'Inspiration', items: credits.inspiration }]" :key="part.title">
				<h4>{{ part.title }}</h4>
				<dl>
					<template v-for="a in part.items" :key="a.name">
						<dt>{{ a.name }}</dt>
						<dd>
							<span v-if="a.what">{{ a.what }}. </span>
							<a v-if="a.url" :href="a.url" target="_blank" rel="noopener noreferrer">{{ a.by }}</a><span v-else>{{ a.by }}</span>
							<span class="license">{{ a.license }}</span>
						</dd>
					</template>
				</dl>
			</section>
		</template>
	</div>
</template>
<script setup lang="ts">
/**
 * The credits, the Help drawer's last section: whose data, pictures, fonts, software and artwork the device uses, and what inspired it (`GET /api/credits`, built from the descriptors and one list on the server).
 * Asked for the first time the section is opened, not every time the drawer is.
 */
import { ref, watch } from "vue"
import { Message } from "primevue"
import { api } from "../api/client"
import type { components } from "../api/schema"

type Credits = components["schemas"]["Credits"]

const props = defineProps<{ active: boolean }>()
const credits = ref<Credits|null>(null)
const failed = ref(false)
watch(() => props.active, active => {
	if (!active || credits.value !== null) return
	failed.value = false
	api.get("/api/credits").then(c => { credits.value = c }).catch(() => { failed.value = true })
}, { immediate: true })
</script>
<style scoped>
.credits {
	display: flex;
	flex-direction: column;
	gap: 0.75rem;
}
.intro, .hint {
	margin: 0;
}
.hint {
	color: var(--p-text-muted-color);
	margin-bottom: 0.5rem;
}
h4 {
	margin: 0 0 0.25rem 0;
}
dl {
	margin: 0;
}
dt {
	font-weight: bold;
}
dd {
	margin: 0 0 0.5rem 0;
}
.kind, .license {
	color: var(--p-text-muted-color);
	font-size: 0.875rem;
	margin-left: 0.5rem;
}
.kind {
	font-weight: normal;
}
a {
	color: var(--p-primary-color);
}
</style>
