"""Public, passive validation using the catalog's supported JSON Schema subset."""

from collections.abc import Mapping
from typing import Any

from hidden_moves import MoveSchemaError
from hidden_moves.core.schema import json_value

from ._validation import ValueValidationError, check_schema, validate_value


def validate_json_value(schema: Mapping[str, Any], value: Any, path: str = "$value") -> Any:
	"""Return a copied finite JSON value matching a supported schema.

	No callable is invoked, defaults are not inserted and values are not coerced.
	Unsupported schemas raise CapabilityExposureError; invalid values raise
	ValueValidationError. Catalog invocation still owns Python signature binding.
	"""
	check_schema(schema)
	try:
		copied = json_value(value)
	except (MoveSchemaError, RecursionError) as error:
		raise ValueValidationError(f"{path}: {error}") from error
	validate_value(schema, copied, path)
	return copied
