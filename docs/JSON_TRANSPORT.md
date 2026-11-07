# Single-document JSON calls

`hm moves call` and `hidden-moves moves call` use the same explicitly selected
catalog as direct Python. Enable a trusted installed provider explicitly.

```sh
printf '%s' '{"value":"hello","count":2}' |
  hm --plugin example-text moves call example.text.repeat --stdin

# The first operation returns a scalar string. Name its next argument explicitly.
set -o pipefail
printf '%s' '{"value":"hello","count":2}' |
  hm --plugin example-text moves call example.text.repeat --stdin |
  hm --plugin example-text moves call example.text.repeat --stdin --input-key value
```

`--stdin` accepts one UTF-8 JSON document of at most 1,048,576 bytes, including
whitespace. Without `--input-key` it must be an argument object. With
`--input-key NAME`, any finite JSON value (including an object, array or null)
becomes the value of that explicit argument. Other parameters use their ordinary
Python defaults. No positional/schema-based conversion is inferred.

`--arguments '{...}'` remains available and uses the same strict parser and size
limit. It is mutually exclusive with `--stdin`; omitting both supplies `{}`.
`--input-key` requires stdin and a nonempty name. Duplicate object keys,
non-finite numbers, exponent overflow, lone Unicode surrogates, multiple documents
and invalid/oversized JSON fail before invocation.

Validated scalar or structured results go to stdout as one UTF-8 JSON document
followed by a newline. Provider-loading and capability Python stdout diagnostics
are redirected to stderr. Result bytes use UTF-8 regardless of the console's
locale encoding. This does not intercept native file-descriptor writes
or background work; trusted providers must own and await their output. Shell
parsing, quoting, expansion and failure propagation belong to the calling shell.
Use its pipe-failure option when the full pipeline must fail if any process fails.

Call errors use stderr and return nonzero. Add `--json-errors` to emit a final
single-line `{"error":{"code":"...","message":"..."}}` record. Trusted provider
or capability diagnostics can precede that record. Messages may include the
capability's exception text; they are diagnostics, not a secret-redaction boundary.
The error record begins on a fresh line even if a diagnostic omitted its newline.

| Code | Exit | Meaning |
| --- | --- | --- |
| `invalid_input` | 2 | Input document, root shape or incompatible call options |
| `invalid_arguments` | 2 | Arguments fail the selected capability contract |
| `unknown_move` | 1 | Name is not registered/selected |
| `unavailable_move` | 1 | Missing binding or unsupported exposure contract |
| `invalid_result` | 1 | Output violates its schema or finite UTF-8 JSON contract |
| `move_error` | 1 | Another structured capability error |
| `execution_failed` | 1 | The capability raised an ordinary exception |

Command parsing and provider-startup failures retain the standard CLI error
contract; `--json-errors` applies to the call boundary after provider loading.
Interrupts retain the CLI's existing interruption behavior. Calls do not retry
or roll back effects. JSON Lines/streaming is not part of this interface.
