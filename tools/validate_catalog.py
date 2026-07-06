#!/usr/bin/env python3
"""Minimal stdlib JSON-Schema validator for catalog.json.

We avoid a jsonschema dependency (stdlib-only rule). This implements just the
draft-07 subset our schema uses: type, required, properties,
additionalProperties, items, enum, pattern, minimum, $ref (local #/definitions),
and additionalProperties-as-schema. It is intentionally small and fails closed.

Usage:
    python3 tools/validate_catalog.py --catalog site/catalog.json --schema schema/catalog.schema.json
Exit 0 = valid, 1 = invalid (errors printed).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TYPES = {
    "object": dict, "array": list, "string": str,
    "integer": int, "number": (int, float), "boolean": bool,
}


class V:
    def __init__(self, root: dict):
        self.root = root
        self.errors: list[str] = []

    def resolve(self, node):
        if isinstance(node, dict) and "$ref" in node:
            ref = node["$ref"]
            assert ref.startswith("#/"), f"only local refs supported: {ref}"
            cur = self.root
            for part in ref[2:].split("/"):
                cur = cur[part]
            return cur
        return node

    def check(self, data, schema, path="$"):
        schema = self.resolve(schema)

        t = schema.get("type")
        if t:
            types = t if isinstance(t, list) else [t]
            # bool is a subclass of int — exclude unless explicitly allowed.
            ok = False
            for tt in types:
                py = TYPES[tt]
                if isinstance(data, py) and not (tt in ("integer", "number") and isinstance(data, bool)):
                    ok = True
            if not ok:
                self.errors.append(f"{path}: expected type {t}, got {type(data).__name__}")
                return

        if "enum" in schema and data not in schema["enum"]:
            self.errors.append(f"{path}: {data!r} not in enum {schema['enum']}")
        if "pattern" in schema and isinstance(data, str):
            if not re.search(schema["pattern"], data):
                self.errors.append(f"{path}: {data!r} does not match /{schema['pattern']}/")
        if "minimum" in schema and isinstance(data, (int, float)):
            if data < schema["minimum"]:
                self.errors.append(f"{path}: {data} < minimum {schema['minimum']}")

        if isinstance(data, dict):
            for req in schema.get("required", []):
                if req not in data:
                    self.errors.append(f"{path}: missing required '{req}'")
            props = schema.get("properties", {})
            addl = schema.get("additionalProperties", True)
            for k, v in data.items():
                if k in props:
                    self.check(v, props[k], f"{path}.{k}")
                elif addl is False:
                    self.errors.append(f"{path}: additional property '{k}' not allowed")
                elif isinstance(addl, dict):
                    self.check(v, addl, f"{path}.{k}")

        if isinstance(data, list) and "items" in schema:
            for i, item in enumerate(data):
                self.check(item, schema["items"], f"{path}[{i}]")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True, type=Path)
    ap.add_argument("--schema", required=True, type=Path)
    args = ap.parse_args(argv)

    schema = json.loads(args.schema.read_text())
    data = json.loads(args.catalog.read_text())
    v = V(schema)
    v.check(data, schema)
    if v.errors:
        print(f"INVALID: {args.catalog}", file=sys.stderr)
        for e in v.errors:
            print(f"  {e}", file=sys.stderr)
        return 1
    print(f"VALID: {args.catalog} ({len(data.get('plugins', []))} plugins)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
