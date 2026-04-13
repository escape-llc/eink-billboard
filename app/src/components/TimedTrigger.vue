<template>
	<div style="display:flex;flex-direction:column;flex-grow:1;justify-content: flex-start;width:100%" class="m-0 p-0">
		<InputGroup>
			<InputGroupAddon>
				<label :style="{'width': fieldNameWidth, 'max-width': fieldNameWidth }" fluid style="flex-shrink:0;flex-grow:1">Run On Startup</label>
			</InputGroupAddon>
			<InputGroupAddon style="flex-grow:1;justify-content:flex-start">
				<Checkbox v-model="editModel.on_startup" size="small" fluid binary
					:name="`${parentPropName}on_startup`" @update:modelValue="onEmitChange('checkbox.on_startup', $event)" />
			</InputGroupAddon>
		</InputGroup>
		<InputGroup>
			<InputGroupAddon>
				<label :style="{'width': fieldNameWidth, 'max-width': fieldNameWidth }" fluid style="flex-shrink:0;flex-grow:1">Day</label>
			</InputGroupAddon>
			<InputGroupAddon style="display:flex;flex-direction:column;flex-grow:1;justify-content:flex-start">
				<Select v-model="editModel.day.type" style="width:100%" size="small" fluid :options="day_options"
					@update:modelValue="onEmitChange('select.day', $event)"
					:name="`${parentPropName}day.type`" optionValue="value" optionLabel="name" />
				<CheckboxGroup v-if="editModel.day.type === 'dayofweek'" v-model="editModel.day.days"
					@value-change="onEmitChange('checkbox.dow', $event)"
					:name="`${parentPropName}day.days`"
					size="small" fluid class="flex flex-wrap gap-1 mt-2" style="flex-grow:1">
					<template v-for="dow in [...Array(7).keys()]" :key="dow">
						<div class="flex items-center gap-2">
							<Checkbox inputId="dow{{ dow }}" :value="dow" />
							<label for="dow{{ dow }}">{{ formatDow(dow) }}</label>
						</div>
					</template>
				</CheckboxGroup>
				<div v-if="editModel.day.type === 'dayofmonth'">Days</div>
				<CheckboxGroup v-if="editModel.day.type === 'dayofmonth'" v-model="editModel.day.days"
					@value-change="onEmitChange('checkbox.day', $event)"
					:name="`${parentPropName}day.days`" size="small" fluid class="flex flex-wrap gap-2 mt-2" style="flex-grow:1;max-width:36rem">
					<template v-for="day in [...Array(31).keys()]" :key="day">
						<div class="flex items-center gap-1">
							<Checkbox inputId="day{{ day }}" :value="day + 1"/>
							<label for="day{{ day }}">{{ day + 1 }}</label>
						</div>
					</template>
					<div class="flex items-center gap-2">
						<Checkbox inputId="dow-1" :value="-1"/>
						<label for="dow-1">End</label>
					</div>
				</CheckboxGroup>
				<DatePicker v-if="editModel.day.type === 'dayandmonth'" v-model="pickerDay" style="width:100%" class="mt-2"
					dateFormat="dd MM"
					size="small" fluid name="day_picker" @update:modelValue="onDatePicker2Change"/>
			</InputGroupAddon>
		</InputGroup>
		<InputGroup>
			<InputGroupAddon>
				<label :style="{'width': fieldNameWidth, 'max-width': fieldNameWidth }" fluid style="flex-shrink:0;flex-grow:1">Time</label>
			</InputGroupAddon>
			<InputGroupAddon style="display:flex;flex-direction:column;flex-grow:1;justify-content:flex-start">
				<Select v-model="editModel.time.type" style="width:100%" size="small" fluid :options="time_options"
					@update:modelValue="onEmitChange('select.time', $event)"
					:name="`${parentPropName}time.type`" optionValue="value" optionLabel="name" />
				<div v-if="editModel.time.type === 'hourofday'">Hours</div>
				<CheckboxGroup v-if="editModel.time.type === 'hourofday'" v-model="editModel.time.hours"
					@value-change="onEmitChange('checkbox.time', $event)"
					:invalid="hoursInvalid"
					:name="`${parentPropName}time.hours`"
					size="small" fluid class="flex flex-wrap gap-2" style="flex-grow:1;max-width:36rem">
					<template v-for="hour in [...Array(24).keys()]" :key="hour">
						<div class="flex items-center gap-1">
							<Checkbox inputId="hour{{ hour }}" :value="hour"/>
							<label for="hour{{ hour }}">{{ hour }}</label>
						</div>
					</template>
				</CheckboxGroup>
				<div v-if="editModel.time.type === 'hourly' || editModel.time.type === 'hourofday'">Minutes</div>
				<CheckboxGroup v-if="editModel.time.type === 'hourly' || editModel.time.type === 'hourofday'" v-model="minutesArray"
					@value-change="onEmitChange('time.minutes', $event)"
					:name="`${parentPropName}time.minutes`"
					size="small" fluid class="flex flex-wrap gap-2" style="flex-grow:1;max-width:36rem">
					<template v-for="minute in [...Array(60).keys()]" :key="minute">
						<div class="flex items-center gap-1">
							<Checkbox inputId="minute{{ minute }}" :value="minute"/>
							<label for="minute{{ minute }}">{{ minute }}</label>
						</div>
					</template>
				</CheckboxGroup>
				<DatePicker v-if="editModel.time.type === 'specific'" v-model="pickerTime" style="width:100%" class="mt-2"
					size="small" fluid name="time_picker" timeOnly @update:modelValue="onDatePickerChange" />
			</InputGroupAddon>
		</InputGroup>
	</div>
</template>
<script setup lang="ts">
import { InputGroup, InputGroupAddon, Select, Checkbox, CheckboxGroup, DatePicker } from "primevue"
import { isProxy, nextTick, provide, reactive, ref, toRaw, watch } from "vue";
import { TriggerDefSchema } from "./ScheduleDefs";

// turns off all the form field context stuff since this component doesn't want it.
// This allows it to be used inside forms without interfering with the form context.
// The parent component can still pass the v-slot="$form" to this component and it will work as expected,
// but this component won't provide any form context to its children.
provide("$pcFormField", undefined)

export interface PropsType {
  modelValue?: any;
	// pass the v-slot="$form" to this prop
//	formContext: any
	fieldNameWidth?: string
	parentPropName: string
}
export interface EmitsType {
//	(e: 'form-field-event', data: SchemaChangeData): void
	(e: 'update:modelValue', trigger: any): void;
	(e: 'change', event: { value: any }): void;
}
function formatDow(dow:number): string {
	const date = new Date(2025, 0, 5 + dow); // January 5, 2025 is a Sunday
	return date.toLocaleDateString('en-US', { weekday: 'narrow' });
}
const props = defineProps<PropsType>()
const emits = defineEmits<EmitsType>()
const editModel = reactive({} as any)
const day_options = ref([{"value": "dayofweek", "name": "Day of Week"}, {"value": "dayofmonth", "name": "Day of Month"}, {"value": "dayandmonth", "name": "Day and Month"	}])
const time_options = ref([{"value": "hourly", "name": "Hourly"}, {"value": "hourofday", "name": "Hour of Day"}, {"value": "specific", "name": "Specific Time"}])
const pickerTime = ref({} as any)
const pickerDay = ref({} as any)
const minutesArray = ref([])
const hoursInvalid = ref(false)

watch(() => props.modelValue, (newVal) => {
	console.log("tt.modelValue changed", newVal);
	if(newVal) {
		Object.assign(editModel, newVal);
		if(newVal.day?.type === 'dayandmonth' && newVal.time?.day !== undefined && newVal.time?.month !== undefined) {
			// create a date object for the date picker with the hour and minute
			const pickerx = new Date(2025, newVal.time.month - 1, newVal.time.day, 0, 0);
			pickerDay.value = pickerx;
		}
		else {
			pickerDay.value = new Date();
		}
		if(newVal.time?.type === 'specific' && newVal.time?.hour !== undefined && newVal.time?.minute !== undefined) {
			// create a date object for the date picker with the hour and minute
			const pickerx = new Date(2025, 0, 1, newVal.time.hour || 0, newVal.time.minute || 0);
			pickerTime.value = pickerx;
		}
		else {
			pickerTime.value = new Date();
		}
		if("minutes" in newVal.time) {
			minutesArray.value = newVal.time.minutes || [];
		}
		else {
			minutesArray.value = [];
		}
		nextTick(() => {
			const result = TriggerDefSchema.safeParse(newVal)
			console.log("tt.iv.result", newVal, result);
			hoursInvalid.value = result.success ? false : !!result.error.issues.find((issue) => issue.path[0] === 'time' && issue.path[1] === 'hours');
		})
	}
}, { immediate: true, deep: true })

function toRawDeep(val: any): any {
  const rawValue = isProxy(val) ? toRaw(val) : val;
  if (Array.isArray(rawValue)) {
    return rawValue.map(toRawDeep);
  }
  
  if (rawValue !== null && typeof rawValue === 'object') {
    const out:any = {};
    for (const key in rawValue) {
      out[key] = toRawDeep(rawValue[key]);
    }
    return out;
  }
  
  return rawValue;
}

const emitChange = () => {
	const vx = structuredClone(toRawDeep(editModel))
	console.log("emitChange", vx);
	emits('update:modelValue', vx)
	emits('change', { value: vx });
}
const onEmitChange = (source: string, ev: any) => {
	console.log("onEmitChange", source, ev)
	switch(source) {
		case 'time.minutes':
			editModel.time.minutes = structuredClone(toRaw(minutesArray.value));
			break;
	}
	emitChange();
}
const onDatePickerChange = (event: any) => {
	// convert the date to an object with hour and minute
	const date: Date = event;
	pickerTime.value = {
		hour: date.getHours(),
		minute: date.getMinutes(),
		day: date.getDate(),
		month: date.getMonth() + 1,
		year: date.getFullYear()
	}
	editModel.time.hour = date.getHours();
	editModel.time.minute = date.getMinutes();
	emitChange();
}
const onDatePicker2Change = (event: any) => {
	// convert the date to an object with day, month, and year
	const date: Date = event;
	pickerDay.value = {
		hour: date.getHours(),
		minute: date.getMinutes(),
		day: date.getDate(),
		month: date.getMonth() + 1,
		year: date.getFullYear()
	}
	editModel.day.day = date.getDate();
	editModel.day.month = date.getMonth() + 1;
	emitChange();
}
</script>
<style scoped>
</style>