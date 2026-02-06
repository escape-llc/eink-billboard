<script setup lang="ts">
import { Listbox, Dialog, InputGroup, InputGroupAddon, Tag, Toast, TieredMenu, Button, Toolbar, ConfirmDialog } from 'primevue';
import { RouterLink, RouterView } from 'vue-router'
import ThemeSelector from './components/ThemeSelector.vue'
import { computed, ref, toRaw } from 'vue';
import { useRouter } from 'vue-router';
import { useToast } from 'primevue';
const router = useRouter();
const toast = useToast();
const menu = ref<InstanceType<typeof TieredMenu>|null>(null)
const toggleMenu = (event:MouseEvent):void => {
	menu.value?.toggle(event);
}
const version = ref(__APP_VERSION__)
const openSetup = (event:MouseEvent):void => {
	console.log("openSetup", event);
	router.push({ name: 'setup' }).catch(err => {
		console.error("navigate to setup error", err);
	});
};
const items = ref([
		{
			label:"Schedule",
			icon: "pi pi-clock",
			class: "p-0 m-0",
//			disabled: () => appStore.currentStateAppConfig !== "initialized",
			to: "/schedule",
		},
		{
			label:"Playlist",
			icon: "pi pi-play",
			class: "p-0 m-0",
//			disabled: () => appStore.currentStateAppConfig !== "initialized",
			to: "/playlist",
		},
		{
			label:"Settings",
			icon: "pi pi-globe",
			class: "p-0 m-0",
//			disabled: () => appStore.currentStateAppConfig !== "initialized",
			to: "/settings",
		},
	]
)
</script>
<template>
	<Toolbar
		class="py-1 px-1 flex items-center justify-center"
	>
	<template #start>
		<div class="flex flex-row" style="flex-grow:1;align-items:center">
		<InputGroup>
			<Button
				v-if="items.length !== 0"
				icon="pi pi-bars"
				size="small"
				class="p-button-outlined"
				type="button"
				aria-haspopup="true"
				aria-controls="overlay_tmenu"
				@click="toggleMenu($event)"
				/>
			<TieredMenu
				id="overlay_tmenu"
				ref="menu"
				:model="items"
				:popup="true"
				style="font-weight:bold">
				<template #item="{ item, props, hasSubmenu }">
					<router-link
						v-if="item.to"
						v-slot="{ href, navigate }"
						:to="item.to"
						custom
					>
							<a
								:href="href"
								v-bind="props.action"
								@click="navigate"
							>
									<span :class="item.icon" />
									<span class="ml-2">{{ item.label }}</span>
							</a>
					</router-link>
					<a
						v-else
						:href="item.url"
						:target="item.target"
						v-bind="props.action"
					>
							<span :class="item.icon" />
							<span class="ml-2">{{ item.label }}</span>
							<span v-if="hasSubmenu" class="pi pi-angle-right ml-auto" />
					</a>
				</template>
			</TieredMenu>
			<!--
			<template v-if="appStore.currentProject !== null">
				<InputGroupAddon>
					<div style="font-weight: bold;font-size: 110%">{{ appStore.currentProject.project.name }}</div>
				</InputGroupAddon>
				<template v-if="openMode === 'open'">
					<Button size="small" icon="pi pi-video" @click="handleAnnotate" />
					<Button size="small" icon="pi pi-database" @click="handleDatabase" />
				</template>
			</template>
			-->
		</InputGroup>
		<div class="flex flex-row p-0 m-0 pl-2" style="flex-grow:1">
			<h2
			class="m-0"
			style="font-size:100%;align-self:baseline;width:6rem">eInk Billboard</h2>
			<span
			class="ml-0"
			style="align-self:baseline">v{{version}}</span>
		</div>
		</div>
	</template>
	<template #center>
		<!--
		<Tag v-if="appStore.currentStateAppConfig !== 'initialized'" class="ml-2" severity="warn" value="Setup Required" title="Setup Required" />
		-->
	</template>
	<template #end>
		<InputGroup>
			<ThemeSelector class="p-button-sm"/>
			<Button
				icon="pi pi-cog"
				class="p-button-sm p-button-outlined"
				type="button"
				aria-haspopup="true"
				aria-controls="overlay_tmenu"
				@click="openSetup($event)"
				/>
			</InputGroup>
	</template>
	</Toolbar>
	<RouterView class="router-view" />
	<ConfirmDialog></ConfirmDialog>
	<Toast position="bottom-left"/>
</template>
<style scoped>
.router-view {
	flex-grow: 1;
	border-radius: var(--p-toolbar-border-radius);
	border: solid 1px var(--p-toolbar-border-color)
}
</style>
<style>
:root {
	--main-toolbar-height: 2.5rem;
}
</style>
