"""CLI parsing and errors at the thin adapter boundary."""

import io
import json
import subprocess
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from importlib.metadata import EntryPoint
from unittest.mock import patch

from hidden_moves import ENTRY_POINT_GROUP, MoveSpec
from hidden_moves.cli import app, main


class CliTests(unittest.TestCase):
	def invoke(self, arguments, data=b""):
		with (
			io.TextIOWrapper(io.BytesIO(), encoding="utf-8") as stdout,
			io.TextIOWrapper(io.BytesIO(), encoding="utf-8") as stderr,
			io.TextIOWrapper(io.BytesIO(data), encoding="utf-8") as stdin,
			redirect_stdout(stdout),
			redirect_stderr(stderr),
			patch("sys.stdin", stdin),
		):
			with self.assertRaises(SystemExit) as exited:
				main(arguments)
			stdout.flush()
			stderr.flush()
			return subprocess.CompletedProcess(arguments, exited.exception.code,
				stdout.buffer.getvalue().decode("utf-8"), stderr.buffer.getvalue().decode("utf-8"))

	def test_help_and_move_listing_do_not_discover_or_execute_providers(self):
		with patch("hidden_moves.cli.discover_providers") as discover:
			for arguments in (["--help"], ["moves", "list"]):
				result = self.invoke(arguments)
				self.assertEqual(result.returncode, 0, result.stderr)
			discover.assert_not_called()
		self.assertEqual(result.stdout, "")
		self.assertEqual(set(app.children), {"plugins", "moves"})
		listing = self.invoke(["moves", "list", "--json"])
		self.assertEqual(json.loads(listing.stdout), [])

	def test_nested_help_does_not_load_explicit_providers(self):
		with (
			patch("hidden_moves.cli.discover_providers") as discover,
			patch("hidden_moves.cli.load_provider") as load,
		):
			for path in ([], ["moves"], ["moves", "list"], ["moves", "show"],
				["moves", "call"], ["plugins"], ["plugins", "list"]):
				with self.subTest(path=path):
					result = self.invoke(["--plugin", "example", *path, "--help"])
					self.assertEqual(result.returncode, 0, result.stderr)
					self.assertIn("usage:", result.stdout)
					self.assertEqual(result.stderr, "")
			discover.assert_not_called()
			load.assert_not_called()

	def test_invalid_commands_fail_before_provider_setup(self):
		with (
			patch("hidden_moves.cli.discover_providers") as discover,
			patch("hidden_moves.cli.load_provider") as load,
		):
			for arguments in ([], ["moves"], ["plugins"], ["moves", "show"], ["moves", "call"],
				["missing"], ["moves", "missing"], ["moves", "list", "--missing"],
				["moves", "call", "name", "--arguments"]):
				with self.subTest(arguments=arguments):
					result = self.invoke(["--plugin", "example", *arguments])
					self.assertEqual(result.returncode, 2, result.stderr)
					self.assertEqual(result.stdout, "")
					self.assertTrue(result.stderr)
			discover.assert_not_called()
			load.assert_not_called()

	def test_domain_commands_are_not_shipped(self):
		for name in ("text", "json", "cmd", "notes"):
			with self.subTest(name=name):
				result = self.invoke([name])
				self.assertEqual(result.returncode, 2)

	@contextmanager
	def provider(self, *specs):
		entry = EntryPoint("example", "example:provide", ENTRY_POINT_GROUP)
		with (
			patch("hidden_moves.cli.discover_providers", return_value=(entry,)),
			patch.object(EntryPoint, "load", return_value=lambda: specs),
		):
			yield

	def test_invalid_json_and_unknown_moves_have_useful_errors(self):
		result = self.invoke(["moves", "call", "unknown", "--arguments", "{broken"])
		self.assertEqual(result.returncode, 2)
		self.assertIn("Invalid value", result.stderr)
		result = self.invoke(["moves", "show", "unknown"])
		self.assertEqual(result.returncode, 1)
		self.assertIn("Unknown move", result.stderr)

	def test_show_reports_a_target_requirement_without_invocation(self):
		def operation(target: str, value: str) -> str:
			return target + value

		with self.provider(MoveSpec("operation", operation, bind_target=True)):
			result = self.invoke(["--plugin", "example", "moves", "show", "operation"])
		self.assertEqual(result.returncode, 0, result.stderr)
		details = json.loads(result.stdout)
		self.assertFalse(details["available"])
		self.assertTrue(details["bind_target"])

	def test_json_listing_reports_schemas_without_invocation(self):
		def operation(value: str) -> str:
			raise AssertionError("listing executed a capability")

		entry = EntryPoint("example", "example:provide", ENTRY_POINT_GROUP)
		with (
			patch("hidden_moves.cli.discover_providers", return_value=(entry,)),
			patch.object(EntryPoint, "load", return_value=lambda: (MoveSpec("operation", operation),)),
		):
			result = self.invoke(["--plugin", "example", "moves", "list", "--json"])
		self.assertEqual(result.returncode, 0, result.stderr)
		definitions = json.loads(result.stdout)
		self.assertEqual([item["name"] for item in definitions], sorted(item["name"] for item in definitions))
		definition = next(item for item in definitions if item["name"] == "operation")
		self.assertEqual(definition["input_schema"]["required"], ["value"])

	def test_generic_call_uses_the_catalog_and_returns_json(self):
		def operation(value: str) -> str:
			return value.upper()

		with self.provider(MoveSpec("operation", operation)):
			result = self.invoke(["--plugin", "example", "moves", "call", "operation", "--arguments", '{"value": "Hello World"}'])
		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertEqual(json.loads(result.stdout), "HELLO WORLD")

	def test_bad_json_and_invalid_arguments_fail_before_execution(self):
		def operation(value: str) -> str:
			raise AssertionError("invalid arguments executed")

		entry = EntryPoint("example", "example:provide", ENTRY_POINT_GROUP)
		with (
			patch("hidden_moves.cli.discover_providers", return_value=(entry,)),
			patch.object(EntryPoint, "load", return_value=lambda: (MoveSpec("operation", operation),)),
		):
			for arguments in ("{broken", "[]", "{}", '{"value": 1}', '{"value": "ok", "extra": 1}'):
				with self.subTest(arguments=arguments):
					result = self.invoke(["--plugin", "example", "moves", "call", "operation", "--arguments", arguments])
					self.assertNotEqual(result.returncode, 0)
					self.assertNotIn("invalid arguments executed", result.stderr)

	def test_generic_call_reports_missing_binding(self):
		def operation(target: str) -> str:
			return target

		with self.provider(MoveSpec("operation", operation, bind_target=True)):
			result = self.invoke(["--plugin", "example", "moves", "call", "operation"])
		self.assertEqual(result.returncode, 1)
		self.assertIn("requires Moves", result.stderr)

	def test_generic_call_awaits_async_providers_in_the_cli(self):
		async def add(value: int) -> int:
			return value + 1

		entry = EntryPoint("example", "example:provide", ENTRY_POINT_GROUP)
		with (
			patch("hidden_moves.cli.discover_providers", return_value=(entry,)),
			patch.object(EntryPoint, "load", return_value=lambda: (MoveSpec("add", add),)),
		):
			result = self.invoke(["--plugin", "example", "moves", "call", "add", "--arguments", '{"value": 2}'])
		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertEqual(json.loads(result.stdout), 3)

	def test_capability_failure_has_a_terminal_error(self):
		def failure() -> None:
			raise RuntimeError("example failure")

		entry = EntryPoint("example", "example:provide", ENTRY_POINT_GROUP)
		with (
			patch("hidden_moves.cli.discover_providers", return_value=(entry,)),
			patch.object(EntryPoint, "load", return_value=lambda: (MoveSpec("failure", failure),)),
		):
			result = self.invoke(["--plugin", "example", "moves", "call", "failure"])
		self.assertEqual(result.returncode, 1)
		self.assertIn("example failure", result.stderr)

	def test_plugin_listing_reads_metadata_without_loading(self):
		entry = EntryPoint("example", "example:provide", ENTRY_POINT_GROUP)
		with (
			patch("hidden_moves.commands.capabilities.discover_providers", return_value=(entry,)),
			patch.object(EntryPoint, "load") as load,
		):
			result = self.invoke(["plugins", "list"])
		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertIn("example:provide", result.stdout)
		load.assert_not_called()

	def test_explicit_plugin_loading_is_scoped_to_one_invocation(self):
		entry = EntryPoint("example", "example:provide", ENTRY_POINT_GROUP)
		with (
			patch("hidden_moves.cli.discover_providers", return_value=(entry,)),
			patch.object(EntryPoint, "load", return_value=lambda: (MoveSpec("upper", str.upper),)),
		):
			loaded = self.invoke(["--plugin", "example", "moves", "show", "upper"])
			self.assertEqual(loaded.returncode, 0, loaded.stderr)
			self.assertEqual(json.loads(loaded.stdout)["source"], "example:provide")
		unloaded = self.invoke(["moves", "show", "upper"])
		self.assertEqual(unloaded.returncode, 1)

	def test_repeated_plugin_options_load_each_selected_provider(self):
		first = EntryPoint("first", "first:provide", ENTRY_POINT_GROUP)
		second = EntryPoint("second", "second:provide", ENTRY_POINT_GROUP)

		def operation() -> str:
			return "ok"

		with (
			patch("hidden_moves.cli.discover_providers", return_value=(first, second)),
			patch.object(EntryPoint, "load", side_effect=[
				lambda: (MoveSpec("second", operation),),
				lambda: (MoveSpec("first", operation),),
			]) as load,
		):
			result = self.invoke(["--plugin", "second", "--plugin", "first", "moves", "list", "--json"])
		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertEqual([item["name"] for item in json.loads(result.stdout)], ["first", "second"])
		self.assertEqual(load.call_count, 2)
		self.assertEqual(json.loads(self.invoke(["moves", "list", "--json"]).stdout), [])

	def test_provider_failure_does_not_leak_state_to_the_next_invocation(self):
		def operation() -> str:
			return "ok"

		with self.provider(MoveSpec("operation", operation)):
			failed = self.invoke(["--plugin", "example", "--plugin", "missing", "moves", "list"])
		self.assertEqual(failed.returncode, 1)
		self.assertEqual(failed.stdout, "")
		self.assertIn("not installed", failed.stderr)
		self.assertEqual(json.loads(self.invoke(["moves", "list", "--json"]).stdout), [])

	def test_interrupts_keep_the_terminal_error_contract(self):
		def interrupt() -> None:
			raise KeyboardInterrupt()

		with self.provider(MoveSpec("interrupt", interrupt)):
			result = self.invoke(["--plugin", "example", "moves", "call", "interrupt"])
		self.assertEqual(result.returncode, 1)
		self.assertEqual(result.stdout, "")
		self.assertIn("Aborted!", result.stderr)
		self.assertNotIn("Traceback", result.stderr)

	def test_missing_and_ambiguous_provider_names_do_not_load_any_package(self):
		entry = EntryPoint("example", "example:provide", ENTRY_POINT_GROUP)
		other = EntryPoint("example", "other:provide", ENTRY_POINT_GROUP)
		for entries in ((), (entry, other)):
			with (
				self.subTest(entries=entries),
				patch("hidden_moves.cli.discover_providers", return_value=entries),
				patch.object(EntryPoint, "load") as load,
			):
				result = self.invoke(["--plugin", "example", "moves", "list"])
				self.assertEqual(result.returncode, 1)
				load.assert_not_called()
