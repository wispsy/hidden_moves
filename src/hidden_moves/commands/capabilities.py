"""Thin Click adapters for explicit capability inspection and invocation."""

import asyncio
import inspect
import json
import sys
from contextlib import redirect_stdout
from typing import Any

import click

from hidden_moves import MoveError, Moves, UnknownMoveError, discover_providers
from hidden_moves.adapters import (
	CapabilityArgumentError, CapabilityCatalog, CapabilityExposureError, CapabilityResultError,
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
		click.echo(json.dumps({"error": {"code": code, "message": message}}), err=True)
	else:
		click.echo(f"Error: {message}", err=True)
	raise click.exceptions.Exit(status)


@click.group(name="moves")
def move_commands() -> None:
	"""Inspect registered capabilities."""


@move_commands.command(name="list")
@click.option("--json", "as_json", is_flag=True, help="Emit complete capability definitions as JSON.")
@click.pass_obj
def list_moves(moves: Moves, as_json: bool) -> None:
	if as_json:
		click.echo(json.dumps([moves.explain(spec.qualified_name) for spec in moves.moves()], indent=2))
		return
	for spec in moves.moves():
		click.echo(f"{spec.qualified_name}\t{spec.summary}")


@move_commands.command(name="show")
@click.argument("name")
@click.pass_obj
def show_move(moves: Moves, name: str) -> None:
	try:
		click.echo(json.dumps(moves.explain(name), indent=2))
	except MoveError as error:
		raise click.ClickException(str(error)) from error


async def _await_result(result: Any) -> Any:
	return await result


@move_commands.command(name="call")
@click.argument("name")
@click.option("--arguments", default=None, help="Arguments as a JSON object (default: {}).")
@click.option("--stdin", "from_stdin", is_flag=True, help="Read one bounded UTF-8 JSON document.")
@click.option("--input-key", default=None, help="Wrap the stdin JSON value under this explicit argument name.")
@click.option("--json-errors", is_flag=True, help="Emit structured call errors on stderr.")
@click.pass_obj
def call_move(moves: Moves, name: str, arguments: str | None, from_stdin: bool,
		input_key: str | None, json_errors: bool) -> None:
	"""Explicitly call one capability through its structured argument contract."""
	try:
		if from_stdin and arguments is not None:
			raise ValueError("--stdin and --arguments are mutually exclusive.")
		if input_key is not None and (not from_stdin or not input_key):
			raise ValueError("--input-key requires --stdin and a nonempty argument name.")
		document = (click.get_binary_stream("stdin").read(MAX_INPUT_BYTES + 1)
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
			catalog = CapabilityCatalog(moves, [name])
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
	click.echo(payload)


@click.group(name="plugins")
def plugin_commands() -> None:
	"""Inspect installed provider metadata."""


@plugin_commands.command(name="list")
def list_plugins() -> None:
	for entry in discover_providers():
		click.echo(f"{entry.name}\t{entry.value}")
