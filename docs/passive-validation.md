# Passive schema validation

`hidden_moves.adapters.validate_json_value(schema, value, path="$value")` validates
the same documented JSON Schema subset as CapabilityCatalog, returning a copied,
finite JSON value. It never invokes a capability, adds defaults or coerces values.
Unsupported schemas raise CapabilityExposureError; invalid values raise the public
ValueValidationError. The optional path labels diagnostics in composing systems.
Catalog invocation remains responsible for signature binding and model conversion.
