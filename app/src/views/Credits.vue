<template>
	<div class="credits-page">
	<Toolbar class="p-1">
		<template #start>
			<div style="font-size:150%">Credits</div>
		</template>
	</Toolbar>
	<div class="credits" data-testid="credits">
		<p class="intro">eInk Billboard shows data, pictures and type made by others. This is everyone it owes, in one place. The Weather pages and the maps also say it on the panel, as those services ask.</p>
		<Message v-if="failed" severity="error" size="small">The credits could not be loaded.</Message>
		<template v-if="credits">
			<section>
				<h3>Data and pictures</h3>
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
				<h3>Fonts</h3>
				<p class="hint">Each shipped unmodified, under the SIL Open Font License 1.1, with its licence beside it.</p>
				<dl>
					<template v-for="f in credits.fonts" :key="f.name">
						<dt>{{ f.name }}</dt>
						<dd>{{ f.by }}</dd>
					</template>
				</dl>
			</section>
			<section>
				<h3>Software</h3>
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
		</template>
	</div>
	</div>
</template>
<script setup lang="ts">
/** The Credits page: whose data, pictures, fonts and software the device uses (`GET /api/credits`, built from the descriptors and one list on the server). */
import { onMounted, ref } from "vue"
import { Message, Toolbar } from "primevue"
import { apiJson } from "../components/ApiClient"

type DataCredit = { id: string, name: string, text: string, license?: string, url?: string, provider: boolean }
type Credit = { name: string, by: string, license: string, url?: string, what?: string }
type Credits = { data: DataCredit[], fonts: Credit[], software: Credit[] }

const credits = ref<Credits|null>(null)
const failed = ref(false)
onMounted(() => {
	apiJson<Credits>("/api/credits").then(c => { credits.value = c }).catch(() => { failed.value = true })
})
</script>
<style scoped>
.credits {
	padding: .75rem 1rem;
	max-width: 50rem;
	display: flex;
	flex-direction: column;
	gap: 1rem;
}
.intro, .hint {
	margin: 0;
}
.hint {
	color: var(--p-text-muted-color);
	margin-bottom: .5rem;
}
h3 {
	margin: 0 0 .25rem 0;
}
dl {
	margin: 0;
	display: grid;
	grid-template-columns: minmax(8rem, 14rem) 1fr;
	gap: .35rem 1rem;
}
dt {
	font-weight: bold;
}
dd {
	margin: 0;
}
.kind, .license {
	color: var(--p-text-muted-color);
	font-size: .875rem;
	margin-left: .5rem;
}
.kind {
	font-weight: normal;
	display: block;
	margin-left: 0;
}
a {
	color: var(--p-primary-color);
}
@media (max-width: 40rem) {
	dl {
		grid-template-columns: 1fr;
	}
	dd {
		margin-bottom: .35rem;
	}
}
</style>
