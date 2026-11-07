# Reusable capability groups

`MoveSet` collects definitions under a namespace. It has no bound target,
pipeline, ordering policy or execution state. Install a group explicitly into
an application's registry, then select exact names for a consumer.

```python
from hidden_moves import Moves, MoveSet
from hidden_moves.adapters import CapabilityCatalog

def normalize(text: str) -> str:
    return " ".join(text.split()).lower()

text = MoveSet("text")
text.learn(normalize)

moves = Moves()
text.install(moves.registry)
catalog = CapabilityCatalog(moves, ["text.normalize"])
assert catalog.invoke("text.normalize", {"text": " Hello  WORLD "}) == "hello world"
```

The group name is a public dotted Python namespace. `learn()` accepts the same
definition options as `Moves.learn()`, including explicit schemas, metadata,
annotations, provider identity and target requirements. Its optional
`namespace=` is relative: `MoveSet("text").learn(fn, namespace="clean")` produces
`text.clean.fn`. Names and collisions follow the existing registry rules.

`moves()` returns the immutable specs in qualified-name order. `describe()`
inspects all definitions without invoking them; target-bound definitions remain
unavailable until an application supplies a compatible target in `Moves`.
Installation preserves each spec and does not share an application's targets.

`install(registry)` validates the whole batch before publishing it. A collision
leaves the destination unchanged. `replace=True` explicitly replaces matching
definitions, while move/namespace conflicts still fail. The installed definitions
are a snapshot: later learning or replacement in the group does not alter an
existing registry or catalog. Reinstall and construct a new catalog explicitly
when the application wants the updated selection.

This class groups capabilities. The separately planned `moveset.Pipeline` will
compose their inputs and outputs; it is not part of Hidden Moves.
