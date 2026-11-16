"""Thin command adapters for explicit capability inspection and invocation."""

import asyncio
import inspect
import json
import sys
from contextlib import redirect_stdout
from typing import Any

from expose_interface import CommandError, Context, Interface, flag, option

from hidden_moves import MoveError, Moves, UnknownMoveError, discover_providers
from hidden_moves.adapters import (
	CapabilityArgumentError,
	CapabilityCatalog,
	CapabilityExposureError,
	CapabilityResultError,
)

MAX_INPUT_BYTES = 1024 * 1024


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
	values = {}
	for key, value in pairs:
		if key in values:
			raise ValueError("Duplicate JSON object key.")
		values[key] = value
	return values


def _reject_constant(value: str) -> None:
	raise ValueError("JSON numbers must be finite.")


def _parse_document(document: bytes) -> Any:
	if len(document) > MAX_INPUT_BYTES:
		raise ValueError(f"JSON input exceeds {MAX_INPUT_BYTES} bytes.")
	try:
		value = json.loads(document.decode("utf-8"), object_pairs_hook=_unique_object,
			parse_constant=_reject_constant)
		# Check exponent overflow and escaped lone surrogates as well as NaN tokens.
		json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")
		return value
	except (ValueError, UnicodeError, RecursionError) as error:
		raise ValueError("Expected one finite UTF-8 JSON document without duplicate keys.") from error


def _call_error(code: str, message: str, status: int, as_json: bool) -> None:
	if as_json:
		# A trusted diagnostic may have omitted its terminating newline.
		print("\n" + json.dumps({"error": {"code": code, "message": message}}), file=sys.stderr)
	else:
		print(f"Error: {message}", file=sys.stderr)
	raise SystemExit(status)


move_commands = Interface("moves", description="Inspect registered capabilities.")
plugin_commands = Interface("plugins", description="Inspect installed provider metadata.")


@move_commands.program(name="list")
@flag("--json", dest="as_json", help="Emit complete capability definitions as JSON.")
def list_moves(context: Context, as_json: bool = False) -> None:
	"""List registered capabilities."""
	moves: Moves = context.obj
	if as_json:
		print(json.dumps([moves.explain(spec.qualified_name) for spec in moves.moves()], indent=2))
		return
	for spec in moves.moves():
		print(f"{spec.qualified_name}\t{spec.summary}")


@move_commands.program(name="show")
def show_move(context: Context, name: str) -> None:
	"""Show a capability's structured definition."""
	try:
		print(json.dumps(context.obj.explain(name), indent=2))
	except MoveError as error:
		raise CommandError(str(error)) from error


async def _await_result(result: Any) -> Any:
	return await result


@move_commands.program(name="call")
@option("--arguments", help="Arguments as a JSON object (default: {}).")
@flag("--stdin", dest="from_stdin", help="Read one bounded UTF-8 JSON document.")
@option("--input-key", help="Wrap the stdin JSON value under this explicit argument name.")
@flag("--json-errors", help="Emit structured call errors on stderr.")
def call_move(context: Context, name: str, arguments: str | None = None, from_stdin: bool = False,
		input_key: str | None = None, json_errors: bool = False) -> None:
	"""Explicitly call one capability through its structured argument contract."""
	try:
		if from_stdin and arguments is not None:
			raise ValueError("--stdin and --arguments are mutually exclusive.")
		if input_key is not None and (not from_stdin or not input_key):
			raise ValueError("--input-key requires --stdin and a nonempty argument name.")
		document = (sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
			if from_stdin else (arguments if arguments is not None else "{}").encode("utf-8"))
		values = _parse_document(document)
		if input_key is not None:
			values = {input_key: values}
		if not isinstance(values, dict):
			raise ValueError("Expected an argument object; use --input-key to wrap a JSON value explicitly.")
	except (ValueError, UnicodeError, OSError) as error:
		source = "--stdin" if from_stdin else "--arguments"
		_call_error("invalid_input", f"Invalid value for {source}: {error}", 2, json_errors)
	try:
		with redirect_stdout(sys.stderr):
			catalog = CapabilityCatalog(context.obj, [name])
			result = catalog.invoke(name, values)
			if inspect.isawaitable(result):
				result = asyncio.run(_await_result(result))
			value = catalog.serialize_result(name, result)
			try:
				payload = json.dumps(value, indent=2, allow_nan=False, ensure_ascii=False)
				payload.encode("utf-8")
			except (ValueError, UnicodeError, RecursionError) as error:
				raise CapabilityResultError("Result must be finite UTF-8 JSON.") from error
	except CapabilityArgumentError as error:
		_call_error("invalid_arguments", str(error), 2, json_errors)
	except CapabilityExposureError as error:
		_call_error("unavailable_move", str(error), 1, json_errors)
	except CapabilityResultError as error:
		_call_error("invalid_result", str(error), 1, json_errors)
	except UnknownMoveError as error:
		_call_error("unknown_move", str(error), 1, json_errors)
	except MoveError as error:
		_call_error("move_error", str(error), 1, json_errors)
	except Exception as error:
		_call_error("execution_failed", f"Capability {name!r} failed: {error}", 1, json_errors)
	output = sys.stdout.buffer
	output.write((payload + "\n").encode("utf-8"))
	output.flush()


@plugin_commands.program(name="list")
def list_plugins() -> None:
	"""List provider metadata without loading provider code."""
	for entry in discover_providers():
		print(f"{entry.name}\t{entry.value}")
