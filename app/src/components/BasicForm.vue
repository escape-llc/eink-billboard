<template>
	<div>
		<Form ref="formRef" v-slot="$form" class="flex flex-column gap-1 w-full sm:w-56" :initialValues="localValues" :resolver
			:validateOnValueUpdate="true" :validateOnBlur="true" @submit="handleSubmit">
			<slot name="header"></slot>
			<!--
			<div>{{  JSON.stringify(localProperties)  }}</div>
			-->
			<template v-if="localProperties.length === 0">
				<slot name="empty"></slot>
			</template>
			<template v-else>
				<slot name="before-fields"></slot>
				<template v-for="field in localProperties" :key="field.name">
					<!--
					<div>{{  JSON.stringify(field)  }}</div>
					-->
					<template v-if="field.type === 'header'">
						<slot name="group-header" v-bind="field">
							<div>{{ field.title }}</div>
						</slot>
					</template>
					<template v-else>
						<BasicFormField :field="field" :formContext="$form" :fieldNameWidth="labelWidth" :baseUrl="baseUrl" :showHelp="showHelp" :newFields="newNames" :fields="localProperties" @form-field-event="handleFormFieldEvent">
						</BasicFormField>
					</template>
				</template>
				<slot name="after-fields"></slot>
				<!-- what the document has and the schema no longer defines: names only (a value can be a secret); saving leaves them out -->
				<section v-if="staleKeys.length" class="stale-fields" aria-label="No longer used" data-testid="stale-fields">
					<div class="stale-heading">No longer used</div>
					<div v-for="key in staleKeys" :key="key" class="stale-field" data-testid="stale-field">
						<span class="stale-name">{{ key }}</span>
						<Tag size="small" severity="secondary" value="left out when you save" />
					</div>
				</section>
			</template>
			<slot name="footer"></slot>
		</Form>
	</div>
</template>
<script setup lang="ts">
import { missingProviders, missingUses } from "./DataSourceUses"
import { apiJson, joinUrl } from "./ApiClient"
//import { InputGroup, ToggleSwitch, InputGroupAddon, InputText, InputNumber, Message, Select } from 'primevue';
import Form, { type FormInstance, type FormSubmitEvent } from "@primevue/forms/form"
import { Tag } from "primevue"
import { ref, toRaw, nextTick, watch, inject, computed, type Ref } from "vue"
import z from "zod"
import BasicFormField, { type FieldEventData } from './BasicFormField.vue'
import { fieldRules, type FormField } from "./FormValidation"
import { hiddenNames } from "./FormVisibility"
import { adaptiveLabelWidth, labelsOf } from "./LabelWidth"
import type { Descriptor, FormDef, FormValues, LookupValue, Owner, PropertiesDef, ResolvedField, ResolvedFieldDef, SchemaChoice, SchemaType } from "./FormDefs"

const formRef = ref<FormInstance & { submit: () => void, reset: () => void, states?: Record<string, { dirty?: boolean }> }>()
// the rules depend on the values (a hidden field is not validated), so they are built per validation
let currentResolver: ((values: FormValues) => z.ZodType<FormValues>)|undefined = undefined;

type AddToSchemaType = (resv: Record<string, z.ZodTypeAny>) => void
type AddInitialValuesType = () => FormValues

export type { Owner }
export interface PropsType {
	form?: FormDef
	initialValues?: FormValues | null
	/** the label column's width as a CSS length (default 10rem), or `adaptive`: as wide as the longest label, so none wraps */
	fieldNameWidth?: string
	baseUrl: string
	/** whose own settings the `settings` lookups of the form choose from (a plugin's instance form: that plugin) */
	owner?: Owner
	beforeFieldsSchema?: AddToSchemaType
	afterFieldsSchema?: AddToSchemaType
	addInitialValues?: AddInitialValuesType
	/** show each field's `description` (its help text) under it; a header button can turn it off where the help is long */
	showHelp?: boolean
	/** for a stored document: mark the fields it lacks (new in the schema), and list what it has that the schema no longer defines (deleted) */
	showChanges?: boolean
}
export interface ValidateEventData {
	result: z.ZodSafeParseResult<FormValues>
	values: FormValues
}
/** What a submit hands the page: the rules' verdict on the values (`result.data` is what to save) and PrimeVue's own event. */
export interface SubmitEventData {
	result: z.ZodSafeParseResult<FormValues> | undefined
	data: FormSubmitEvent
}
export interface EmitsType {
	(e: 'validate', data: ValidateEventData): void
	(e: 'submit', data: SubmitEventData): void
}

const props = withDefaults(defineProps<PropsType>(), { fieldNameWidth: "10rem", showHelp: true })
/** The label column's width: the prop as given, or, for `adaptive`, wide enough for the longest label of the form (see LabelWidth.ts). */
const labelWidth = computed(() => props.fieldNameWidth === "adaptive" ? adaptiveLabelWidth(labelsOf(localProperties.value)) : props.fieldNameWidth)
// The form reports what happened (`validate`: it checked its values, which may be more than once per change and also when it loads; `submit`); it never
// decides what happens next. Saving, discarding, a conflict and leaving belong to the editor around it (useEditor).
const emits = defineEmits<EmitsType>()
const localProperties = ref<ResolvedField[]>([])
const localValues = ref<FormValues>({})
/** How deep a choice inside a choice goes (a plugin's data source, then the parts it chooses): the server's MAX_CHOICE_DEPTH (documents.py). Before the `immediate` watches, which use it. */
const MAX_CHOICE_DEPTH = 3
const injplugins = inject<Ref<Descriptor[]>>("settingsPluginsList", ref([]))
const injdataSources = inject<Ref<Descriptor[]>>("settingsDataSourcesList", ref([]))
const injdisplays = inject<Ref<Descriptor[]>>("settingsDisplaysList", ref([]))
const plugins = computed<Descriptor[]>(() => injplugins.value)
const dataSources = computed<Descriptor[]>(() => injdataSources.value)
const displays = computed<Descriptor[]>(() => injdisplays.value)
watch(() => props.form, (nv) => {
	if(nv) {
		// a plugin just chosen brings fields the values do not have: they start at the descriptor's default, as they do for a new item
		deepDefaults(nv.schema, props.owner)
		ensureInitializeForm(nv.schema)
		// the rules are new: check the values against them and report it (values that came before the schema were not checked; an editor's baseline is
		// the first report after a load, which must not wait for the user's first edit)
		nextTick().then(_ => formRef.value?.validate())
	}
	else {
		localProperties.value = []
		currentResolver = undefined
	}
}, { immediate:true }
)
watch(() => props.initialValues, (nv) => {
	if(nv) {
		let ox = structuredClone(toRaw(nv))
		if(props.addInitialValues) {
			const addv = props.addInitialValues()
			ox = Object.assign(ox, addv) // ensure new object reference to trigger form update
		}
		// the fields a data source brings depend on the value that chooses it: take the new values first, or the defaults are those of the previous track's source
		localValues.value = ox
		// a value the document does not have yet starts at the descriptor's default (a new playlist track, say)
		if(props.form?.schema) {
			deepDefaults(props.form.schema, props.owner)
		}
		ensureInitializeForm(props.form?.schema)
	}
	else {
		localValues.value = {}
	}
	nextTick().then(_ => {
		formRef.value?.reset();
		formRef.value?.validate();
	});
}, { immediate:true }
)
function ensureInitializeForm(schema: SchemaType|undefined): void {
	if(!schema) return;
	localProperties.value = formProperties(schema, props.owner)
	currentResolver = createResolver(localProperties.value)
	startLookups(schema, localProperties.value)
}
function startLookups(schema: SchemaType, values: ResolvedField[]): void {
	values.forEach(px => {
		// a lookup with parameters is fetched by its field (or its row) for the values it needs, not once here
		if(px.type !== "header" && px.lookup && px.listType === "url" && !px.lookupWith && !px.lookupSearch) {
			lookupUrl(px)
		}
		if(px.children) {
			startLookups(schema, px.children)
		}
		// the fields of a list's rows may choose from a lookup too
		if(px.type === "array" && px.items && "properties" in px.items) {
			startLookups(schema, px.items.properties)
		}
	})
}
function schemaFilterFeatures(features: string[]|undefined, check: string[]|undefined): boolean {
	if(!features || features.length === 0) return false;
	if(!check || check.length === 0) return true;
	return check.some(c => features.includes(c))
}
function formProperties(schema: SchemaType|undefined, owner: Owner|undefined): ResolvedField[] {
	if(schema?.properties) {
		const retv: ResolvedField[] = []
		// a list's row fields are resolved too (they may have a lookup); a header has nothing to resolve
		const resolve = (px: PropertiesDef): ResolvedField => {
			if(px.type === "header") return { ...px }
			const { items, ...rest } = px
			const fx: ResolvedFieldDef = items?.type === "object" ? { ...rest, items: { ...items, properties: items.properties.map(resolve) as ResolvedFieldDef[] } } : { ...rest, items }
			if(px.lookup) {
				if(isLookupItems(schema, px.lookup, "items")) {
					fx.list = lookupItems(schema, px.lookup)
					fx.listType = "items"
				}
				else if(isLookupItems(schema, px.lookup, "url")) {
					fx.list = []
					fx.listType = "url"
					const urlLookup = schema.lookups ? schema.lookups[px.lookup] : undefined
					fx.lookupUrl = urlLookup && 'url' in urlLookup ? urlLookup.url : null
					if(urlLookup && 'url' in urlLookup) {
						if(urlLookup.with?.length) fx.lookupWith = [...urlLookup.with]
						if(urlLookup.search) fx.lookupSearch = true
					}
				}
				else if(isLookupItems(schema, px.lookup, "settings")) {
					// the choices are a list the owner keeps in its own settings: served by the owner's lookup route
					fx.list = []
					fx.listType = "url"
					fx.lookupUrl = owner ? `/api/${owner.kind}s/${encodeURIComponent(owner.id)}/lookups/${encodeURIComponent(px.lookup)}` : null
				}
				else if(isLookupItems(schema, px.lookup, "schema")) {
					fx.list = lookupSchema(schema, px.lookup)
					fx.listType = "schema"
				}
				else {
					console.warn("Unknown lookup type", px.lookup)
				}
			}
			return fx
		}
		schema.properties.forEach(px => {
			const fx = resolve(px)
			if(px.type === "schema" && fx.listType === "schema") {
				const svalue = localValues.value[px.name]
				if(svalue) {
					const target = schemaChoices(fx).find(vx => vx.value === svalue)
					if(target) {
						fx.children = formProperties(target.schema?.schema, target.owner)
						fx.usesMissing = missingUses(target.uses, dataSources.value)
						fx.providersMissing = missingProviders(target.requires, dataSources.value)
					}
				}
			}
			retv.push(fx)
		})
		return retv
	}
	return []
}
/** A `schema` field's choices (its list holds only those). */
function schemaChoices(field: ResolvedField): SchemaChoice[] {
	return field.listType === "schema" ? (field.list ?? []) as SchemaChoice[] : []
}
function isLookupItems(schema: SchemaType, lookup:string, prop:string): boolean {
	if(schema.lookups) {
		const lookups = schema.lookups
		if(lookup in lookups) {
			const lku = lookups[lookup]
			if(lku && prop in lku) {
				return true
			}
		}
	}
	return false
}
function lookupItems(schema: SchemaType, lookup:string): LookupValue[] {
	if(schema.lookups) {
		const lookups = schema.lookups
		if(lookup in lookups) {
			const lku = lookups[lookup]
			if(lku && "items" in lku) {
				const items = toRaw(lku.items)
				const result = items.map(mx=>structuredClone(mx))
				return result
			}
		}
	}
	return []
}
function lookupSchema(schema: SchemaType, lookup:string): SchemaChoice[] {
 if(schema.lookups) {
		const lookups = schema.lookups
		if(lookup in lookups) {
			const lku = lookups[lookup]
			if(lku && "schema" in lku) {
				if(lku.schema === "plugins") {
					return plugins.value.filter(px => schemaFilterFeatures(px.features, lku.features)).map(px => ({ name: px.name, value: px.id, schema: toRaw(px.instanceSettings), owner: { kind: "plugin", id: px.id } }))
				}
				else if(lku.schema === "data-sources") {
					return dataSources.value.filter(px => schemaFilterFeatures(px.features, lku.features)).map(px => ({ name: px.name, value: px.id, schema: toRaw(px.instanceSettings), uses: px.uses, requires: px.requires, features: px.features, keepsList: px.keepsList === true, owner: { kind: "datasource", id: px.id } }))
				}
				else if(lku.schema === "displays") {
					return displays.value.filter(px => schemaFilterFeatures(px.features, lku.features)).map(px => ({ name: px.name, value: px.id, schema: toRaw(px.instanceSettings), features: px.features, owner: { kind: "display", id: px.id } }))
				}
				else {
					console.warn("Unknown lookup schema", lku.schema)
				}
			}
		}
	}
	return [];
}
function lookupUrl(target: ResolvedField): void {
	if(target.type === "header") return;
	if(!target.lookupUrl) return;
	const finalUrl = joinUrl(props.baseUrl, target.lookupUrl)
	apiJson<LookupValue[]>(finalUrl).then(json => {
		nextTick().then(_ => {
			target.list = withCurrentValue(json, target.name)
			target.lookupError = undefined
		})
	})
	.catch(ex => {
		console.error("lookupUrl", ex)
		nextTick().then(_ => {
			// the message is shown under the field; it is never a choice that could be saved
			target.list = withCurrentValue([], target.name)
			target.lookupError = `The choices could not be loaded: ${ex.message}`
		})
	})
}
/** A stored value the list does not offer (renamed, or the list failed to load) must still show, not silently look unset; each of a multi-select's too. */
function withCurrentValue(list: LookupValue[], name: string): LookupValue[] {
	const value = localValues.value?.[name]
	const missing = (Array.isArray(value) ? value : [value])
		.filter(current => current !== undefined && current !== null && current !== "" && !list.some(lx => lx.value === current))
	return [...list, ...missing.map(current => ({ name: String(current), value: current }))]
}
function createResolver(fields: FormField[]): (values: FormValues) => z.ZodType<FormValues> {
	return (values) => {
		const resv: Record<string, z.ZodTypeAny> = {}
		if(props.beforeFieldsSchema) {
			props.beforeFieldsSchema(resv)
		}
		fieldRules(fields, resv, values)
		if(props.afterFieldsSchema) {
			props.afterFieldsSchema(resv)
		}
		return z.object(resv)
	}
}
// what the server reported per field: `path` (after the field's name) names the row and field of a list's problem
const serverErrors: Record<string, { message: string, path: string[], value: string }[]> = {}
let lastSubmitted: FormValues = {}
/** Show the `errors` of a 422 response (`[{ path: [name], message }]`) on their fields. Returns how many matched a field of this form. */
const setServerErrors = (errors: { path?: unknown[], message?: string }[]): number => {
	const values = lastSubmitted
	let matched = 0
	const fresh = new Set<string>()
	for(const e of errors ?? []) {
		const name = Array.isArray(e?.path) ? e.path[0] : undefined
		if(typeof name === "string" && typeof e.message === "string") {
			if(!fresh.has(name)) {
				fresh.add(name)
				serverErrors[name] = []
			}
			serverErrors[name]!.push({ message: e.message, path: (e.path as unknown[]).slice(1).map(String), value: JSON.stringify(values?.[name]) })
			matched++
		}
	}
	nextTick().then(_ => formRef.value?.validate())
	return matched
}
/**
 * The values the rules read: what the form holds, and for a field of the schema it does not hold yet the value the form opened with (defaults included).
 * A field mounts only after the field it depends on is set (`visibleIf`), so for a moment it is in the schema and not in the form's values: it must not be
 * judged missing then, and a field the document lacks is the schema's to fill, not to ignore.
 */
function withSchemaValues(values: FormValues): FormValues {
	const complete = { ...values }
	for(const name of flatNames(localProperties.value)) {
		if(complete[name] === undefined && localValues.value?.[name] !== undefined) complete[name] = localValues.value[name]
	}
	return complete
}
const resolver = ({ values: held }: { values: FormValues }) => {
	const errors: Record<PropertyKey, { message: string, path: string[] }[]> = {};
	const values = held
	if(!currentResolver) return { values, errors };
	const complete = withSchemaValues(held)
	const result = currentResolver(complete).safeParse(complete);
	if(!result.success) {
		result.error.issues.forEach(issue => {
			const field = issue.path[0];
			if(field !== undefined) {
				(errors[field] ??= []).push({ message: issue.message, path: issue.path.slice(1).map(String) });
			}
		});
	}
	// problems the server reported stay on a field until its value changes
	for(const [name, entries] of Object.entries(serverErrors)) {
		if(JSON.stringify(values[name]) !== entries[0]!.value) {
			delete serverErrors[name]
		}
		else if(!errors[name]) {
			errors[name] = entries.map(entry => ({ message: entry.message, path: entry.path }))
		}
	}
	emits('validate', { result, values: complete });
	return {
		values, // (Optional) Used to pass current form values to submit event.
		errors
	};
}
const handleSubmit = (data: FormSubmitEvent) => {
	lastSubmitted = data.values ?? {}
	const complete = withSchemaValues(data.values ?? {})
	const result = currentResolver?.(complete)?.safeParse(complete);
	if(result?.success) {
		// a hidden field is not applicable: it is saved as null
		const saved = result.data as Record<string, unknown>
		hiddenNames(localProperties.value, complete).forEach(name => { saved[name] = null })
	}
	emits('submit', { result, data });
}
const submit = () => {
	formRef.value?.submit();
}
const reset = () => {
	formRef.value?.reset();
}
// function declarations, not consts: the `immediate` watches above run during setup, before a const here would be initialized
function flatNames(fields: FormField[]): string[] {
	return fields.flatMap(f => [...(f.type === "header" ? [] : [f.name]), ...flatNames(f.children ?? [])])
}
/** The field of that name at any depth (a data source's own fields can hold another choice). */
function findField(fields: FormField[], name: string): FormField|undefined {
	for(const f of fields) {
		if(f.type !== "header" && f.name === name) return f
		const inner = findField(f.children ?? [], name)
		if(inner) return inner
	}
	return undefined
}
/**
 * Every default the values lack, at any depth: a default that chooses a data source (a Generated Image's parts) brings that source's fields,
 * whose defaults apply in turn. Set on `localValues`, which the fields are built from (`formProperties` reads a choice there).
 */
function deepDefaults(schema: SchemaType|undefined, owner: Owner|undefined): void {
	for(let pass = 0; pass <= MAX_CHOICE_DEPTH; pass++) {
		const more = applyDefaults(formProperties(schema, owner), localValues.value)
		if(more.length === 0) return
		more.forEach(([name, value]) => { localValues.value[name] = value })
	}
}
/** The `default` of each field (null and absent defaults carry no information), for values the form does not have yet. */
function applyDefaults(fields: FormField[], values: FormValues = {}): [string, unknown][] {
	return fields.flatMap(f => [
		...(f.type !== "header" && f.default !== undefined && f.default !== null && !(f.name in values) ? [[f.name, f.default] as [string, unknown]] : []),
		...applyDefaults(f.children ?? [], values)
	])
}
const handleFormFieldEvent = (data: FieldEventData) => {
	if(data.type === "set-value") {
		formRef.value?.setFieldValue(data.field.name, data.value)
	}
	else if(data.type === "schema-change") {
		const field = findField(localProperties.value, data.field.name)
		if(field) {
			// the previous choice's values must not be saved with the new one
			flatNames(field.children ?? []).forEach(name => formRef.value?.setFieldValue(name, null))
			const chosen = data.selected?.schema?.schema
			field.children = formProperties(chosen, data.selected?.owner)
			field.usesMissing = missingUses(data.selected?.uses, dataSources.value)
			field.providersMissing = missingProviders(data.selected?.requires, dataSources.value)
			// the new fields register with the form when they render: a value set before then is dropped (setFieldValue ignores an unknown field),
			// so each default is also where a new field reads its first value, and is set again once the fields are there.
			// Every default of the new choice applies (not the previous choice's value of a field of the same name), and a default that chooses
			// a data source in turn (the Generated Image's parts) brings that source's fields, so the fields are built again until nothing new is chosen
			const defaults: [string, unknown][] = []
			const applied = new Set<string>()
			for(let pass = 0; pass <= MAX_CHOICE_DEPTH; pass++) {
				const more = applyDefaults(field.children ?? []).filter(([name]) => !applied.has(name))
				if(more.length === 0) break
				more.forEach(([name, value]) => {
					applied.add(name)
					defaults.push([name, value])
					localValues.value[name] = value
					formRef.value?.setFieldValue(name, value)
				})
				field.children = formProperties(chosen, data.selected?.owner)
			}
			currentResolver = createResolver(localProperties.value)
			if(chosen) startLookups(chosen, field.children ?? [])
			nextTick().then(_ => {
				defaults.forEach(([name, value]) => formRef.value?.setFieldValue(name, value))
				formRef.value?.validate();
			})
		}
	}
}
/** What the stored document has and the schema no longer defines (a property that was removed or renamed). `_`-keys are the document's own (`_id`, `_rev`); a `null` is unset, with nothing to lose (a hidden field is saved so), so it is not listed. */
const staleKeys = computed<string[]>(() => {
	if(!props.showChanges || !props.initialValues) return []
	const known = new Set(flatNames(localProperties.value))
	return Object.keys(props.initialValues).filter(key => !key.startsWith("_") && !known.has(key) && props.initialValues![key] !== null)
})
/** What the schema defines and the stored document lacks (a property added since it was saved): it starts at its default and is marked. A document with no properties yet is new, and everything in it would be too. */
const newNames = computed<Set<string>>(() => {
	const held = props.initialValues as Record<string, unknown> | undefined
	if(!props.showChanges || !held || Object.keys(held).every(key => key.startsWith("_"))) return new Set()
	return new Set(flatNames(localProperties.value).filter(name => !(name in held)))
})
const isDirty = computed(() => Object.values<{ dirty?: boolean }>(formRef.value?.states ?? {}).some(st => st.dirty))
/** Put a value in a field (a restored default); the form is then changed, and the user saves it or not. */
const setValue = (name: string, value: unknown) => formRef.value?.setFieldValue(name, value)
defineExpose({ submit, reset, setServerErrors, isDirty, setValue })
</script>
<style scoped>
.stale-fields {
	margin-top: .5rem;
	opacity: .6;
}
.stale-heading {
	font-weight: bold;
	font-size: .85rem;
	text-transform: uppercase;
	letter-spacing: .04rem;
}
.stale-field {
	display: flex;
	align-items: center;
	gap: .5rem;
	padding: .2rem 0;
	text-decoration: line-through;
}
.stale-field :deep(.p-tag) {
	text-decoration: none;
}
</style>