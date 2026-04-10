<template>
	<Button v-bind="$attrs" icon="pi pi-palette" severity="contrast" title="Theme Control" aria-label="Theme Control" @click="openPopover" />
	<Popover ref="op">
		<div class="flex flex-column gap-2 mb-2">
			<label for="theme" class="font-bold block mb-0">Theme</label>
			<SelectButton id="theme" v-model="currentTheme" optionLabel="name" :options="themeList" size="small" @change="handleCurrentTheme" />
			<label for="mode" class="font-bold block mb-0">Mode</label>
			<SelectButton id="mode" v-model="currentMode" optionLabel="name" :options="modeList" size="small" @change="handleCurrentMode" />
			<label for="primary" class="font-bold block mb-0">Primary</label>
			<div class="select-panel">
				<template v-for="item in primaryList">
					<button type="button"
						:class="{ 'active-color': item.value === currentPrimary.value }" class="primary-button"
						:style="styleFor(item)" :title="item.name" @click="handleCurrentPrimary(item)" />
				</template>
			</div>
			<label for="surface" class="font-bold block mb-0">Surface</label>
			<div class="select-panel">
				<template v-for="item in surfaceList">
					<button type="button"
						:class="{ 'active-color': item.value === currentSurface.value }" class="primary-button"
						:style="styleFor(item)" :title="item.name" @click="handleCurrentSurface(item)" />
				</template>
			</div>
		</div>
	</Popover>
</template>
<script setup>
import Button from 'primevue/button'
import Popover from 'primevue/popover'
import SelectButton from 'primevue/selectbutton'
import { getTheme, presetForTheme, saveTheme, applyMode, CustomSurfaces } from './ThemeTools'
import { ref } from 'vue'

import { usePreset } from '@primeuix/themes';
import Aura from '@primeuix/themes/aura';
import Nora from '@primeuix/themes/nora';
import Material from '@primeuix/themes/material';
import Lara from '@primeuix/themes/lara';

const op = ref()
const themeList = ref([
	{name: "Material", value: Material },
	{name: "Aura", value: Aura },
	{name: "Nora", value: Nora },
	{name: "Lara", value: Lara },
])
const theme = getTheme()
const selected = theme ? themeList.value.find(fx => fx.name == theme.name) : themeList.value[1]
console.log("theme, selected", theme, selected)
const currentTheme = ref(selected)

const modeList = ref([
	{name:"Auto", value: "auto"},
	{name:"Dark", value: "dark"},
	{name:"Light", value: "light"},
])
const selectedMode = theme ? modeList.value.find(fx => fx.value == theme.mode) : modeList.value[0]
const currentMode = ref(selectedMode)

const primaryList = ref([
	{name:"Emerald", value: "emerald"},
	{name:"Green", value: "green"},
	{name:"Lime", value: "lime"},
	{name:"Orange", value: "orange"},
	{name:"Amber", value: "amber"},
	{name:"Yellow", value: "yellow"},
	{name:"Teal", value: "teal"},
	{name:"Cyan", value: "cyan"},
	{name:"Sky", value: "sky"},
	{name:"Blue", value: "blue"},
	{name:"Indigo", value: "indigo"},
	{name:"Violet", value: "violet"},
	{name:"Purple", value: "purple"},
	{name:"Fuchsia", value: "fuchsia"},
	{name:"Pink", value: "pink"},
	{name:"Rose", value: "rose"},
])
const selectedPrimary = theme ? primaryList.value.find(fx => fx.value == theme.primary) : primaryList.value[9]
const currentPrimary = ref(selectedPrimary)

const surfaceList = ref([
	{name:"Slate", value: "slate", color: "var(--p-slate-500)" },
	{name:"Gray", value: "gray", color: "var(--p-gray-500)" },
	{name:"Zinc", value: "zinc", color: "var(--p-zinc-500)" },
	{name:"Neutral", value: "neutral", color: "var(--p-neutral-500)" },
	{name:"Stone", value: "stone", color: "var(--p-stone-500)" },
	{name:CustomSurfaces[0].name, value: CustomSurfaces[0].value, color: CustomSurfaces[0].palette[500] },
	{name:CustomSurfaces[1].name, value: CustomSurfaces[1].value, color: CustomSurfaces[1].palette[500] },
	{name:CustomSurfaces[2].name, value: CustomSurfaces[2].value, color: CustomSurfaces[2].palette[500] },
])
const selectedSurface = theme ? surfaceList.value.find(fx => fx.value == theme.surface) : surfaceList.value[0]
const currentSurface = ref(selectedSurface)

const openPopover = ev => {
	op.value.toggle(ev);
}
function updateThePreset() {
	const theme = currentTheme.value;
	const mode = currentMode.value;
	const primary = currentPrimary.value;
	const surface = currentSurface.value;
	//console.log("updateThePreset", theme, mode, primary, surface);
	const obj = saveTheme(undefined, theme.name, mode.value, primary.value, surface.value);
	const preset = presetForTheme(obj);
	console.log("saveTheme", obj, preset);
	usePreset(preset);
}
const handleCurrentTheme = ev => {
	console.log("handleCurrentTheme", currentTheme.value);
	updateThePreset();
}
const handleCurrentMode = ev => {
	console.log("handleCurrentMode", currentMode.value);
	applyMode(currentMode.value.value);
	updateThePreset();
}
const handleCurrentPrimary = item => {
	console.log("handleCurrentPrimary", item);
	currentPrimary.value = item;
	updateThePreset();
}
const handleCurrentSurface = item => {
	console.log("handleCurrentSurface", item);
	currentSurface.value = item;
	updateThePreset();
}

const styleFor = item => {
	const color = "color" in item ? item.color : `var(--p-${item.value}-500)`;
	return {
		"background-color": color
	};
}

if(!theme && selected) {
	saveTheme(undefined, selected.name);
}
if(selected) {
	handleCurrentTheme();
}
</script>
<style lang="css" scoped>
.primary-button {
	margin:0;
	padding:0;
	width:1.25rem;
	height:1.25rem;
	border-radius:.75rem;
	border:none;
}
.select-panel {
	display:flex;
	flex-wrap: wrap;
	flex-direction: row;
	max-width: 15rem;
	gap: .25rem;
}
.active-color {
	outline-color: var(--primary-color);
	outline-offset: 1px;
	outline-style: solid;
	outline-width: 2px;
}
</style>