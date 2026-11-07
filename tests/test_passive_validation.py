"""Composition can validate catalog schemas without calling an operation."""

import unittest

from hidden_moves.adapters import CapabilityExposureError, ValueValidationError, validate_json_value


class PassiveValidationTests(unittest.TestCase):
	def test_preserves_values_and_copies_nested_records(self):
		original = {"items": [1, "hello"]}
		copied = validate_json_value({"type": "object"}, original)
		copied["items"].append(2)
		self.assertEqual(original, {"items": [1, "hello"]})
		self.assertEqual(validate_json_value({"type": "integer"}, 2.0), 2.0)
		self.assertEqual(validate_json_value({"default": 3}, None), None)

	def test_uses_supported_subset_and_reports_value_paths(self):
		with self.assertRaises(CapabilityExposureError):
			validate_json_value({"minimum": 1}, 2)
		for value in (True, "2"):
			with self.assertRaisesRegex(ValueValidationError, "step.count"):
				validate_json_value({"type": "integer"}, value, "step.count")
		for value in (float("nan"), float("inf"), {"nested": float("nan")}, object()):
			with self.assertRaises(ValueValidationError):
				validate_json_value({}, value)
