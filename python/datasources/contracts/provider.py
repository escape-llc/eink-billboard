"""
What every contract has in common (#513): a **provider** supplies a capability (a `data-*` feature in its descriptor) by implementing that capability's
contract, a subclass of `ProviderContract`; a data source that needs the capability says so (`requires`) and asks for it with `dsec.provide(Contract)`,
which chooses among the providers that are loaded (`DataSourceExecutionContext.provide`). A consumer imports only contracts, never a provider's module.
"""
from datetime import datetime
from typing import Any, ClassVar, Mapping

from ..data_source import DataSource, DataSourceApi, DataSourceExecutionContext

def device_now(timestamp: datetime) -> datetime:
	"""The slot's time where the display is: the schedule's timestamp carries the system zone (naive means local)."""
	return timestamp if timestamp.tzinfo is not None else timestamp.astimezone()

class ProviderContract(DataSource, DataSourceApi):
	"""
	The base of a capability's contract. `capability` is the feature its providers list; `noun` names it in a message ("No weather provider is set up");
	`setting` is the system setting that names the device's provider of it (None: every use chooses one, as the AI parts are chosen); `tokens` are the fields a
	prompt may use for its data (`tokensFrom: ["<capability>"]` resolves to them), filled by a function of the contract's module from the answer.
	"""
	capability: ClassVar[str] = ""
	noun: ClassVar[str] = ""
	setting: ClassVar[str|None] = None
	tokens: ClassVar[tuple[Mapping[str, str], ...]] = ()

	def configured(self, dsec: DataSourceExecutionContext) -> bool:
		"""Whether its own settings are complete (a key is set where it needs one): never whether its last call worked. `dsec` is its own context."""
		return True

	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> Any:
		# not abstract: `dsec.use(id, Contract)` and `dsec.provide(Contract)` take the class itself
		raise NotImplementedError
