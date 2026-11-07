"""Reusable capability groups without execution or application state."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .definition import MoveAnnotations, MoveDefinition
from .moves import Moves
from .registry import Registry
from .spec import MoveSpec, _validate_component


class MoveSet:
	"""Collect definitions under a namespace and explicitly install them together.

	A set has no bound target or execution state. Installing it copies definitions
	into an application's registry; each Moves container supplies its own target.
	Namespaces passed to learn() are relative to the set's name.
	"""

	__slots__ = ("_name", "_moves")

	def __init__(self, name: str) -> None:
		if not isinstance(name, str):
			raise TypeError("A MoveSet name must be a dotted string.")
		for component in name.split("."):
			_validate_component(component)
		self._name = name
		self._moves = Moves()

	@property
	def name(self) -> str:
		return self._name

	def learn(
		self,
		func: Callable[..., Any],
		*,
		name: str | None = None,
		namespace: str | None = None,
		bind_target: bool = False,
		target_types: tuple[type, ...] = (),
		description: str | None = None,
		provider: str | None = None,
		annotations: MoveAnnotations | None = None,
		metadata: Mapping[str, Any] | None = None,
		input_schema: Mapping[str, Any] | None = None,
		output_schema: Mapping[str, Any] | None = None,
		replace: bool = False,
	) -> MoveSpec:
		if namespace is not None and not isinstance(namespace, str):
			raise TypeError("A relative namespace must be a dotted string or None.")
		qualified = self.name if namespace is None else f"{self.name}.{namespace}"
		return self._moves.learn(
			func, name=name, namespace=qualified, bind_target=bind_target,
			target_types=target_types, description=description, provider=provider,
			annotations=annotations, metadata=metadata, input_schema=input_schema,
			output_schema=output_schema, replace=replace,
		)

	def moves(self) -> tuple[MoveSpec, ...]:
		"""Return definitions in qualified-name order without executing them."""
		return self._moves.moves()

	def describe(self) -> tuple[MoveDefinition, ...]:
		"""Inspect all definitions; target-bound operations remain unbound here."""
		return tuple(self._moves.describe(spec.qualified_name) for spec in self.moves())

	def install(self, registry: Registry, *, replace: bool = False) -> tuple[MoveSpec, ...]:
		"""Install a snapshot atomically; later learning does not alter the registry."""
		if not isinstance(registry, Registry):
			raise TypeError("MoveSet.install expects a Registry.")
		return registry.register_many(self.moves(), replace=replace)
