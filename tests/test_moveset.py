"""Reusable groups preserve the registry and catalog contracts."""

import unittest

from hidden_moves import MoveAnnotations, MoveCollisionError, Moves, MoveSet, Registry
from hidden_moves.adapters import CapabilityCatalog


def normalize(text: str) -> str:
	return " ".join(text.split()).lower()


class MoveSetTests(unittest.TestCase):
	def test_group_installs_without_execution_and_has_deterministic_order(self):
		def report(text: str) -> dict[str, int]:
			raise AssertionError("inspection executed a move")

		group = MoveSet("text")
		group.learn(report)
		group.learn(normalize)
		self.assertEqual(group.name, "text")
		self.assertEqual([item.name for item in group.describe()], ["text.normalize", "text.report"])
		moves = Moves()
		self.assertEqual(group.install(moves.registry), group.moves())
		self.assertEqual(moves.text.normalize(" Hello  WORLD "), "hello world")
		catalog = CapabilityCatalog(moves, ["text.normalize"])
		self.assertEqual(catalog.invoke("text.normalize", {"text": " A  B "}), "a b")

	def test_relative_and_dotted_namespaces_remain_explicit(self):
		group = MoveSet("example.text")
		group.learn(normalize, namespace="clean", name="spaces")
		self.assertEqual(group.moves()[0].qualified_name, "example.text.clean.spaces")
		for namespace in ("", ".nested", "nested.", "_private", "for", 1):
			with self.subTest(namespace=namespace), self.assertRaises((ValueError, TypeError)):
				group.learn(normalize, namespace=namespace)
		self.assertEqual(len(group.moves()), 1)

	def test_invalid_names_are_rejected(self):
		for name in ("", ".text", "text.", "text..more", "_private", "for", "has space", None, 3):
			with self.subTest(name=name), self.assertRaises((TypeError, ValueError)):
				MoveSet(name)

	def test_binding_and_metadata_are_preserved_across_targets(self):
		def prefix(target: str, text: str) -> str:
			return target + text

		metadata = {"labels": ["example"]}
		annotations = MoveAnnotations(read_only=True)
		group = MoveSet("text")
		spec = group.learn(prefix, bind_target=True, target_types=(str,),
			metadata=metadata, annotations=annotations, provider="example")
		metadata["labels"].append("changed")
		definition, = group.describe()
		self.assertFalse(definition.available)
		self.assertEqual(definition.metadata["labels"], ("example",))
		self.assertEqual(definition.annotations, annotations)
		registry = Registry()
		group.install(registry)
		self.assertIs(registry.resolve("text.prefix"), spec)
		first = Moves("first: ", registry=registry)
		second = Moves("second: ", registry=registry)
		self.assertEqual(first.text.prefix("hello"), "first: hello")
		self.assertEqual(second.text.prefix("hello"), "second: hello")
		self.assertFalse(Moves(1, registry=registry).describe("text.prefix").available)

	def test_installation_is_atomic_on_collision(self):
		group = MoveSet("text")
		group.learn(normalize, name="first")
		group.learn(normalize, name="last")
		moves = Moves()
		moves.learn(normalize, namespace="text", name="last")
		before = moves.moves()
		with self.assertRaises(MoveCollisionError):
			group.install(moves.registry)
		self.assertEqual(moves.moves(), before)
		self.assertFalse(moves.knows("text.first"))

	def test_namespace_collision_remains_atomic_even_with_replacement(self):
		group = MoveSet("text")
		group.learn(normalize)
		moves = Moves()
		moves.learn(normalize, name="text")
		with self.assertRaises(MoveCollisionError):
			group.install(moves.registry, replace=True)
		self.assertEqual([spec.qualified_name for spec in moves.moves()], ["text"])

	def test_learning_and_installation_have_explicit_replacement_and_snapshot_semantics(self):
		group = MoveSet("text")
		group.learn(normalize)
		with self.assertRaises(MoveCollisionError):
			group.learn(normalize)
		moves = Moves()
		group.install(moves.registry)
		group.learn(str.upper, name="normalize", replace=True)
		group.learn(normalize, name="another")
		self.assertFalse(moves.knows("text.another"))
		self.assertEqual(moves.text.normalize(" A "), "a")
		group.install(moves.registry, replace=True)
		self.assertEqual(moves.text.normalize("hello"), "HELLO")

	def test_explicit_schemas_survive_installation(self):
		group = MoveSet("text")
		group.learn(lambda value: value, name="echo",
			input_schema={"type": "object", "properties": {"value": {"type": "string"}},
				"required": ["value"], "additionalProperties": False},
			output_schema={"type": "string"})
		moves = Moves()
		group.install(moves.registry)
		catalog = CapabilityCatalog(moves, ["text.echo"])
		self.assertEqual(catalog.serialize_result("text.echo", catalog.invoke("text.echo", {"value": "hi"})), "hi")

	def test_empty_group_and_invalid_install_target(self):
		group = MoveSet("text")
		self.assertEqual(group.describe(), ())
		self.assertEqual(group.install(Registry()), ())
		with self.assertRaises(TypeError):
			group.install(Moves())
