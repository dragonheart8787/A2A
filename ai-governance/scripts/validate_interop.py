#!/usr/bin/env python3
"""
AI ↔ AI 互通層驗證：interop 目錄下所有 YAML/JSON 依 schemas 機驗。
可單獨執行或由 CI 呼叫。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, ValidationError

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GOVERNANCE = REPO_ROOT / "ai-governance"
INTEROP = GOVERNANCE / "interop"
SCHEMAS = INTEROP / "schemas"


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def validate_one(data: dict, schema: dict, label: str) -> list[str]:
    errors: list[str] = []
    try:
        validator = Draft202012Validator(schema)
        for err in validator.iter_errors(data):
            errors.append(f"{label}: {err.message}")
    except Exception as e:
        errors.append(f"{label}: schema error - {e}")
    return errors


def main() -> int:
    if not INTEROP.exists():
        print("interop/ 不存在，跳過互通層驗證。")
        return 0

    all_errors: list[str] = []

    # 1) agents/*.yaml -> agent-identity.json
    schema_path = SCHEMAS / "agent-identity.json"
    if schema_path.exists():
        schema = load_json(schema_path)
        for p in (INTEROP / "agents").glob("*.yaml"):
            data = load_yaml(p)
            if data.get("spec") == "agent-identity":
                all_errors.extend(validate_one(data, schema, f"agents/{p.name}"))

    # 2) tasks/*.yaml -> task-ticket.json
    schema_path = SCHEMAS / "task-ticket.json"
    if schema_path.exists():
        schema = load_json(schema_path)
        for p in (INTEROP / "tasks").glob("*.yaml"):
            data = load_yaml(p)
            if data.get("spec") == "task-ticket":
                all_errors.extend(validate_one(data, schema, f"tasks/{p.name}"))

    # 3) artifacts-registry.yaml -> artifact-registry.json
    reg_path = INTEROP / "artifacts-registry.yaml"
    schema_path = SCHEMAS / "artifact-registry.json"
    if reg_path.exists() and schema_path.exists():
        data = load_yaml(reg_path)
        if data.get("spec") == "artifact-registry":
            schema = load_json(schema_path)
            all_errors.extend(validate_one(data, schema, "artifacts-registry.yaml"))

    # 4) coordination-protocol.yaml
    proto_path = INTEROP / "coordination-protocol.yaml"
    schema_path = SCHEMAS / "coordination-protocol.json"
    if proto_path.exists() and schema_path.exists():
        data = load_yaml(proto_path)
        if data.get("spec") == "coordination-protocol":
            schema = load_json(schema_path)
            all_errors.extend(validate_one(data, schema, "coordination-protocol.yaml"))

    # 5) conflict-ownership.yaml
    conflict_path = INTEROP / "conflict-ownership.yaml"
    schema_path = SCHEMAS / "conflict-ownership.json"
    if conflict_path.exists() and schema_path.exists():
        data = load_yaml(conflict_path)
        if data.get("spec") == "conflict-ownership":
            schema = load_json(schema_path)
            all_errors.extend(validate_one(data, schema, "conflict-ownership.yaml"))

    # 6) security-trust.yaml
    sec_path = INTEROP / "security-trust.yaml"
    schema_path = SCHEMAS / "security-trust.json"
    if sec_path.exists() and schema_path.exists():
        data = load_yaml(sec_path)
        if data.get("spec") == "security-trust":
            schema = load_json(schema_path)
            all_errors.extend(validate_one(data, schema, "security-trust.yaml"))

    for e in all_errors:
        print(e, file=sys.stderr)
    if all_errors:
        return 1
    print("Interop 驗證通過。")
    return 0


if __name__ == "__main__":
    sys.exit(main())