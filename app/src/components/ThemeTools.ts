import { definePreset } from '@primevue/themes';
import Aura from '@primevue/themes/aura';
import Nora from '@primevue/themes/nora';
import Material from '@primevue/themes/material';
import Lara from '@primevue/themes/lara';

const DEBUG = false;
// tracks current state of media query
let inDarkMode: boolean|undefined = undefined;
// CSS style used on HTML element to select Dark Mode
const DARK_MODE_CSS = "app-dark-mode";
// Dark Mode CSS selector
const DARK_MODE_SELECTOR = `.${DARK_MODE_CSS}`;
type ThemeListEntry = { name: String, value: any };
// theme master list
const ThemeList: ThemeListEntry[] = [
	{name: "Material", value: Material },
	{name: "Aura", value: Aura },
	{name: "Nora", value: Nora },
	{name: "Lara", value: Lara },
];
const CustomSurfaces = [
	{
		name: 'Soho',
		value: 'soho',
		palette: { 0: '#ffffff', 50: '#ececec', 100: '#dedfdf', 200: '#c4c4c6', 300: '#adaeb0', 400: '#97979b', 500: '#7f8084', 600: '#6a6b70', 700: '#55565b', 800: '#3f4046', 900: '#2c2c34', 950: '#16161d' }
	},
	{
		name: 'Viva',
		value: 'viva',
		palette: { 0: '#ffffff', 50: '#f3f3f3', 100: '#e7e7e8', 200: '#cfd0d0', 300: '#b7b8b9', 400: '#9fa1a1', 500: '#87898a', 600: '#6e7173', 700: '#565a5b', 800: '#3e4244', 900: '#262b2c', 950: '#0e1315' }
	},
	{
		name: 'Ocean',
		value: 'ocean',
		palette: { 0: '#ffffff', 50: '#fbfcfc', 100: '#F7F9F8', 200: '#EFF3F2', 300: '#DADEDD', 400: '#B1B7B6', 500: '#828787', 600: '#5F7274', 700: '#415B61', 800: '#29444E', 900: '#183240', 950: '#0c1920' }
	}
];
// default to Aura theme
const DefaultTheme = ThemeList[1];
const STORAGE_KEY = "theme-" + __APP_PACKAGE__;
const MODE_AUTO = "auto";
const MODE_LIGHT = "light";
const MODE_DARK = "dark";
const DEFAULT_NAME = DefaultTheme?.name;
const DEFAULT_MODE = MODE_AUTO;
const DEFAULT_PRIMARY = "blue";
const DEFAULT_SURFACE = "slate";
// default settings storage version (PresetConfig)
const DefaultThemeStorage = {
	name: DEFAULT_NAME,
	/** @type { 'auto' | 'dark' | 'light' } */
	mode: DEFAULT_MODE,
	primary: DEFAULT_PRIMARY,
	surface: DEFAULT_SURFACE,
};
/**
 * Apply the theme mode.
 * @param {String} mode the mode light|dark|auto
 */
const applyMode = (mode: string) => {
	DEBUG && console.log("applyMode", mode, inDarkMode);
	switch(mode) {
		case MODE_LIGHT:
			document.documentElement.classList.remove(DARK_MODE_CSS);
			break;
		case MODE_DARK:
			document.documentElement.classList.add(DARK_MODE_CSS);
			break;
		case MODE_AUTO:
			if(inDarkMode) {
				// dark
				document.documentElement.classList.add(DARK_MODE_CSS);
			}
			else {
				// light
				document.documentElement.classList.remove(DARK_MODE_CSS);
			}
			break;
	}
}
/**
 * Return a palette for the given surface design token.
 * @param {String} color theme color token.
 * @returns new instance.
 */
function surfaceFor(color: string) {
	const custom = CustomSurfaces.find(cx => cx.value === color);
	if(custom) return custom.palette;
	return {
		0: "#ffffff",
		50: `{${color}.50}`,
		100: `{${color}.100}`,
		200: `{${color}.200}`,
		300: `{${color}.300}`,
		400: `{${color}.400}`,
		500: `{${color}.500}`,
		600: `{${color}.600}`,
		700: `{${color}.700}`,
		800: `{${color}.800}`,
		900: `{${color}.900}`,
		950: `{${color}.950}`
	};
}
/**
 * Return a palette for the given primary design token.
 * @param {String} color theme color token.
 * @returns new instance.
 */
function primaryFor(color: string) {
	return {
		50: `{${color}.50}`,
		100: `{${color}.100}`,
		200: `{${color}.200}`,
		300: `{${color}.300}`,
		400: `{${color}.400}`,
		500: `{${color}.500}`,
		600: `{${color}.600}`,
		700: `{${color}.700}`,
		800: `{${color}.800}`,
		900: `{${color}.900}`,
		950: `{${color}.950}`
	};
}
/**
 * Return components config overrides.
 * @param {PresetConfig} preset 
 * @returns new instance.
 */
function componentsFor(preset: any) {
	return {
		panel: {
			colorScheme: {
				light: {
					'header.background': "{surface.100}"
				},
				dark: {
					'header.background': "{surface.950}"
				}
			}
		}
	};
}
/**
 * Return a PrimeVue theme preset for the given config.
 * @param {PresetConfig} preset 
 * @returns new preset.
 */
function presetFor(preset: any) {
	const surface = surfaceFor(preset.surface ?? DEFAULT_SURFACE);
	const components = componentsFor(preset);
	return {
		components,
		semantic: {
				primary: primaryFor(preset.primary ?? DEFAULT_PRIMARY),
				colorScheme: {
					light: {
						surface
					},
					dark: {
						surface
					}
				}
		}
	};
}
/**
 * Consult with local storage for the PresetConfig.
 * @param {String|undefined} key storage key or UNDEFINED for default key.
 * @returns !NULL: found in local storage; NULL: not found.
 */
const getTheme = (key?: string) => {
	const skey = key ?? STORAGE_KEY;
	const json = localStorage.getItem(skey);
	if(!json) return null;
	const obj = JSON.parse(json);
	DEBUG && console.log("getTheme.storage", skey, obj);
	return obj;
}
/**
 * Take individual properties, create PresetConfig, save to local storage.
 * @param {String|undefined} name the LocalStorage key or UNDEFINED for the default key.
 * @param {String|undefined} name the theme name.
 * @param {light|dark|auto|undefined} mode the mode.
 * @param {String|undefined} primary the primary color token.
 * @param {String|undefined} surface the surface token.
 * @returns new PresetConfig
 */
const saveTheme = (key?: string, name?: string, mode?: string, primary?: string, surface?: string) => {
	const obj = {
		name: name ?? DEFAULT_NAME,
		mode: mode ?? DEFAULT_MODE,
		primary: primary ?? DEFAULT_PRIMARY,
		surface: surface ?? DEFAULT_SURFACE
	};
	const skey = key ?? STORAGE_KEY;
	DEBUG && console.log("saveTheme.storage", skey, obj);
	localStorage.setItem(skey, JSON.stringify(obj));
	return obj;
}
/**
 * Create a PrimeVue theme preset from config.
 * @param {PresetConfig} config the settings.
 * @returns ThemePreset
 */
const presetForTheme = (config: any) => {
	const target = ThemeList.find(tl => tl.name == config.name) ?? DefaultTheme;
	const presets = presetFor(config);
	const output = definePreset(target.value, presets);
	DEBUG && console.log("presetForTheme", config, presets, output);
	return output;
}
/**
 * Initialize the theme support and start watching CSS media query.
 * @param {{key:String}} options additional options.
 * @returns {{DefaultPreset: any, DARK_MODE_SELECTOR: String}} theme info.
 */
const useThemes = (options:any) => {
	// Get PresetConfig from local storage or copy of defaults
	const activeTheme = getTheme(options?.key) ?? structuredClone(DefaultThemeStorage);
	const prefersDarkTheme = window.matchMedia('(prefers-color-scheme: dark)');
	function _handleDarkTheme(evt: any) {
		inDarkMode = evt.matches;
		const activeTheme = getTheme(options?.key) ?? DefaultThemeStorage;
		DEBUG && console.log("prefersDarkTheme.change", evt, activeTheme);
		applyMode(activeTheme.mode ?? DEFAULT_MODE);
	}
	// Handle the current state
	_handleDarkTheme(prefersDarkTheme);
	// Listen for future changes
	prefersDarkTheme.addEventListener("change", _handleDarkTheme);
	const DefaultPreset = presetForTheme(activeTheme);
	return { DefaultPreset, DARK_MODE_SELECTOR };
}

export { useThemes, getTheme, saveTheme, presetForTheme, applyMode, CustomSurfaces }