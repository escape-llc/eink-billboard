<template>
	<Dialog :visible="true" @update:visible="(visible: boolean) => { if (!visible) emit('close') }" modal :header="title" style="width:60%; min-width:min(36rem, 95vw); font-size:90%">
		<Message v-if="!plugin" severity="warn" size="small" :closable="false">The {{ pluginId }} plugin is not installed on this device.</Message>
		<BasicForm v-else ref="form" :form="plugin.instanceSettings" :owner="{ kind: 'plugin', id: plugin.id }" :initialValues="content ?? undefined" :baseUrl="baseUrl" :showHelp="showHelp" class="form" @submit="submitted">
			<template #header>
				<Toolbar style="width:100%" class="p-1 mt-2">
					<template #start>
						<div style="font-weight: bold;font-size:150%">{{ plugin.name }}</div>
					</template>
					<template #end>
						<InputGroup>
							<HelpToggle v-model="showHelp" />
							<Button size="small" icon="mi mi-check" severity="success" aria-label="Apply" title="Use these settings" @click="form?.submit()" />
							<Button size="small" icon="mi mi-close" severity="danger" aria-label="Cancel" title="Close without changing" @click="emit('close')" />
						</InputGroup>
					</template>
				</Toolbar>
			</template>
			<template #group-header="slotProps">
				<h3 class="mb-0">{{ slotProps.title }}</h3>
			</template>
		</BasicForm>
	</Dialog>
</template>
<script setup lang="ts">
/**
 * The settings a list row carries for a plugin (`items.plugin` of a list, see FormDefs.ts): the plugin's own form in a dialog, as a timer task's. Apply hands back the checked values;
 * Cancel leaves the row as it was.
 */
import { computed, ref } from "vue"
import { Button, Dialog, InputGroup, Message, Toolbar } from "primevue"
import { useCatalog } from "../api/resources"
import BasicForm from "./BasicForm.vue"
import HelpToggle from "./HelpToggle.vue"
import type { FormValues } from "./FormDefs"

const props = defineProps<{ pluginId: string, title: string, content: FormValues | null, baseUrl: string }>()
const emit = defineEmits<{ (e: "apply", values: FormValues): void, (e: "close"): void }>()
const catalog = useCatalog()
const plugin = computed(() => (catalog.plugins.data.value ?? []).find(p => p.id === props.pluginId))
const form = ref<InstanceType<typeof BasicForm>>()
const showHelp = ref(true)
function submitted({ result }: { result?: { success: boolean, data?: FormValues } }) {
	// plain data: the values are the form's own reactive objects, which the editor that holds the list cannot copy
	if (result?.success && result.data) emit("apply", JSON.parse(JSON.stringify(result.data)))
}
</script>
