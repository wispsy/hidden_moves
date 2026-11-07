"""Actual process pipes and strict single-document call boundaries."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


class StdioTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.directory = tempfile.TemporaryDirectory()
		root = Path(cls.directory.name)
		(root / "stdio_fixture.py").write_text(textwrap.dedent('''\
			from hidden_moves import MoveSet
			def normalize(text: str) -> str:
			    print("function diagnostic")
			    return " ".join(text.split()).lower()
			async def report(text: str) -> dict[str, int]:
			    return {"words": len(text.split()), "characters": len(text)}
			def echo(value: dict[str, int]) -> dict[str, int]:
			    return value
			def failure() -> None:
			    print("partial failure diagnostic", end="")
			    raise RuntimeError("synthetic failure")
			def invalid() -> list[int]:
			    return {1}
			def provide_moves():
			    print("provider diagnostic", end="")
			    group = MoveSet("text")
			    for function in (normalize, report, echo, failure, invalid):
			        group.learn(function)
			    return group.moves()
		'''), encoding="utf-8")
		metadata = root / "stdio_fixture-0.1.dist-info"
		metadata.mkdir()
		(metadata / "entry_points.txt").write_text(
			"[hidden_moves.moves]\nstdio-fixture = stdio_fixture:provide_moves\n", encoding="utf-8")
		source = Path(__file__).resolve().parents[1] / "src"
		cls.env = {**os.environ, "PYTHONPATH": os.pathsep.join((str(root), str(source))),
			"PYTHONIOENCODING": "utf-8"}
		cls.command = [sys.executable, "-m", "hidden_moves", "--plugin", "stdio-fixture", "moves", "call"]

	@classmethod
	def tearDownClass(cls):
		cls.directory.cleanup()

	def call(self, name, *options, data=b""):
		return subprocess.run([*self.command, name, *options], input=data,
			capture_output=True, env=self.env, timeout=15)

	def error_code(self, result):
		self.assertEqual(result.stdout, b"")
		# Provider diagnostics may precede the structured error record.
		return json.loads(result.stderr.splitlines()[-1])["error"]["code"]

	def test_two_actual_processes_pipe_scalar_output_into_explicit_argument(self):
		with subprocess.Popen([*self.command, "text.normalize", "--stdin"],
			stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env) as first:
			with subprocess.Popen([*self.command, "text.report", "--stdin", "--input-key", "text"],
				stdin=first.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env) as second:
				first.stdout.close()
				first.stdin.write(b'{"text":" Hello   WORLD "}')
				first.stdin.close()
				output, diagnostics = second.communicate(timeout=15)
				first_diagnostics = first.stderr.read()
				self.assertEqual(first.wait(timeout=15), 0, first_diagnostics)
				self.assertEqual(second.returncode, 0, diagnostics)
		self.assertEqual(json.loads(output), {"words": 2, "characters": 11})
		self.assertIn(b"function diagnostic", first_diagnostics)
		self.assertIn(b"provider diagnostic", diagnostics)

	def test_object_arguments_and_explicit_record_wrapping(self):
		result = self.call("text.echo", "--stdin", "--input-key", "value", data=b'{"a":2}')
		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertEqual(json.loads(result.stdout), {"a": 2})

	def test_unicode_is_utf8_and_scalar_mapping_is_never_inferred(self):
		data = json.dumps({"text": "  HÉLLO 🍑 "}, ensure_ascii=False).encode("utf-8")
		result = self.call("text.normalize", "--stdin", data=data)
		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertEqual(json.loads(result.stdout), "héllo 🍑")
		result = self.call("text.normalize", "--stdin", "--json-errors", data=b'"hello"')
		self.assertEqual(result.returncode, 2)
		self.assertEqual(self.error_code(result), "invalid_input")

	def test_result_bytes_are_utf8_even_with_a_non_utf8_stdout_encoding(self):
		result = subprocess.run([*self.command, "text.normalize", "--stdin"],
			input=json.dumps({"text": " HÉLLO 🍑 "}).encode("ascii"),
			capture_output=True, env={**self.env, "PYTHONIOENCODING": "cp1252"}, timeout=15)
		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertIn("🍑".encode("utf-8"), result.stdout)
		self.assertEqual(json.loads(result.stdout), "héllo 🍑")

	def test_invalid_documents_fail_before_invocation(self):
		for data in (b"", b"{broken", b"{} {}", b'{"text":"a","text":"b"}',
			b'{"text":NaN}', b'{"text":1e999}', b'{"text":"\\ud800"}', b"\xff",
			b"[" * 1500, b" " * (1024 * 1024 + 1)):
			with self.subTest(data=data[:30]):
				result = self.call("text.normalize", "--stdin", "--json-errors", data=data)
				self.assertEqual(result.returncode, 2, result.stderr)
				self.assertEqual(self.error_code(result), "invalid_input")
				self.assertNotIn(b"function diagnostic", result.stderr)

	def test_invalid_shapes_and_incompatible_options_fail_before_invocation(self):
		for options, data, code in (
			(("--stdin",), b'{"text":3}', "invalid_arguments"),
			(("--stdin", "--arguments", "{}"), b"{}", "invalid_input"),
			(("--input-key", "text"), b"", "invalid_input"),
			(("--stdin", "--input-key", ""), b"{}", "invalid_input"),
			(("--arguments", '{"text":"a","text":"b"}'), b"", "invalid_input"),
		):
			with self.subTest(options=options):
				result = self.call("text.normalize", *options, "--json-errors", data=data)
				self.assertEqual(result.returncode, 2, result.stderr)
				self.assertEqual(self.error_code(result), code)
				self.assertNotIn(b"function diagnostic", result.stderr)

	def test_failures_have_stable_error_codes_and_empty_stdout(self):
		for name, code in (("missing", "unknown_move"), ("text.failure", "execution_failed"),
			("text.invalid", "invalid_result")):
			with self.subTest(name=name):
				result = self.call(name, "--json-errors")
				self.assertEqual(result.returncode, 1, result.stderr)
				self.assertEqual(self.error_code(result), code)
