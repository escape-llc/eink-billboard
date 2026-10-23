const MS_PER_DAY = 86400000;
const MS_PER_HOUR = 1000*60*60;
const MS_PER_MINUTE = 1000*60;

function midnight(dx:Date):Date {
	const start = new Date(dx.getTime());
	start.setHours(0);
	start.setMinutes(0);
	start.setSeconds(0);
	start.setMilliseconds(0);
	return start;
}

class DateBuilder {
	_date: Date
	constructor(date: Date) {
		this._date = date;
	}
	date(): Date { return this._date; }
	midnight(): DateBuilder {
		this._date = midnight(this._date)
		return this;
	}
	minutes(minutes: number): DateBuilder {
		this._date = new Date(this._date.getTime() + minutes*MS_PER_MINUTE)
		return this;
	}
	hours(hours: number): DateBuilder {
		this._date = new Date(this._date.getTime() + hours*MS_PER_HOUR)
		return this;
	}
	days(days: number): DateBuilder {
		this._date = new Date(this._date.getTime() + days*MS_PER_DAY)
		return this;
	}
}
export { MS_PER_DAY, MS_PER_HOUR, MS_PER_MINUTE, DateBuilder }