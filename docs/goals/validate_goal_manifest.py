#!/usr/bin/env python3
"""Validate a JSON-compatible YAML goal manifest using the bundled schema."""

import argparse
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.json")
PLACEHOLDER = re.compile(r"\{\{[^{}]+\}\}")
RFC3339_DATE_TIME = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[Tt]"
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})"
    r"(?P<fraction>\.\d+)?(?P<zone>[Zz]|[+-]\d{2}:\d{2})$"
)


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True, stderr=subprocess.STDOUT).strip()


def type_matches(value, expected):
    names = expected if isinstance(expected, list) else [expected]
    checks = {
        "null": value is None,
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
    }
    return any(checks.get(name, False) for name in names)


def is_rfc3339_date_time(value):
    """Apply JSON Schema's RFC 3339 date-time format without dependencies."""
    match = RFC3339_DATE_TIME.fullmatch(value)
    if not match:
        return False
    # RFC 3339 permits a leap second. Python's parser does not, so validate
    # the surrounding calendar/time/offset after normalizing only that second.
    if int(match.group("second")) > 60:
        return False
    zone = match.group("zone")
    if zone not in {"Z", "z"}:
        offset_hour, offset_minute = (int(part) for part in zone[1:].split(":"))
        if offset_hour > 23 or offset_minute > 59:
            return False
    normalized = value
    if match.group("fraction"):
        start, end = match.span("fraction")
        # Python's accepted precision is an implementation detail; RFC 3339
        # permits one or more digits. Syntax is already checked, so use a
        # representative fraction solely for calendar/time validation.
        normalized = f"{normalized[:start]}.000000{normalized[end:]}"
    if match.group("second") == "60":
        start, end = match.span("second")
        normalized = f"{normalized[:start]}59{normalized[end:]}"
    if normalized[-1] in "Zz":
        normalized = f"{normalized[:-1]}+00:00"
    try:
        datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return True


def schema_errors(value, schema, path="$", root=None):
    """Validate the bounded JSON Schema vocabulary used by schema.json."""
    errors = []
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: value must equal {schema['const']!r}")
    if "type" in schema and not type_matches(value, schema["type"]):
        return [f"{path}: wrong type; expected {schema['type']}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value is not in the allowed set")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: string is too short")
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            errors.append(f"{path}: string does not match required pattern")
        if schema.get("format") == "date-time" and not is_rfc3339_date_time(value):
            errors.append(f"{path}: invalid date-time")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: array has too few items")
        for index, item in enumerate(value):
            errors.extend(schema_errors(item, schema.get("items", {}), f"{path}[{index}]", root))
    if isinstance(value, dict):
        required = schema.get("required", [])
        errors.extend(f"{path}: missing required field: {key}" for key in required if key not in value)
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            errors.extend(f"{path}: unexpected field: {key}" for key in value if key not in properties)
        for key, child in value.items():
            if key in properties:
                errors.extend(schema_errors(child, properties[key], f"{path}.{key}", root))
    return errors


def validate(path, repo=None, schema_path=SCHEMA_PATH):
    errors = []
    try:
        raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"manifest is not JSON-compatible YAML: {exc}"]
    try:
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"schema is invalid JSON: {exc}"]
    if PLACEHOLDER.search(raw):
        errors.append("unresolved placeholder")
    errors.extend(schema_errors(data, schema))
    if repo and isinstance(data, dict):
        try:
            identities = {
                "repository": git(repo, "rev-parse", "--show-toplevel"),
                "branch": git(repo, "branch", "--show-current"),
                "head": git(repo, "rev-parse", "HEAD"),
            }
            for key, expected in identities.items():
                if data.get(key) != expected:
                    errors.append(f"{key if key != 'head' else 'HEAD'} mismatch")
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"identity check failed: {exc}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--repo", type=Path, help="check repository, branch, and HEAD identity")
    parser.add_argument("--schema", type=Path, default=SCHEMA_PATH)
    args = parser.parse_args()
    errors = validate(args.manifest, args.repo, args.schema)
    if errors:
        for error in errors:
            print(error)
        raise SystemExit(1)
    print("valid")


if __name__ == "__main__":
    main()
