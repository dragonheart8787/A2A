#!/usr/bin/env python3
"""
Machine-checkable schema 驗證：所有 spec block 必須通過對應 JSON Schema。
CI 與 pre-commit 呼叫此腳本；失敗則 exit 1。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, ValidationError

# 專案根目錄 = ai-governance 的上一層
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GOVERNANCE = REPO_ROOT / "ai-governance"
SCHEMAS = GOVERNANCE / "schemas"


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def extract_spec_blocks(md_path: Path) -> list[tuple[str, str, dict]]:
    """從 .md 抽出 ```yaml ... ``` 區塊，回傳 [(spec_type_version, raw, parsed), ...]"""
    text = md_path.read_text(encoding="utf-8")
    pattern = re.compile(r"```yaml\s*\n(.*?)```", re.DOTALL)
    blocks = []
    for m in pattern.finditer(text):
        raw = m.group(1).strip()
        # 第一行可能是 # spec:contract v1
        first = raw.split("\n")[0].strip()
        if first.startswith("# spec:"):
            spec_tag = first.replace("#", "").strip().split()
            if len(spec_tag) >= 2:
                type_ver = spec_tag[0] + " " + spec_tag[1]
            else:
                type_ver = first
        else:
            type_ver = ""
        try:
            parsed = yaml.safe_load(raw) or {}
        except yaml.YAMLError as e:
            blocks.append((type_ver, raw, None))
            print(f"  YAML parse error in {md_path}: {e}", file=sys.stderr)
            continue
        blocks.append((type_ver, raw, parsed))
    return blocks


def get_schema_for_spec(spec_type_version: str) -> Path | None:
    """spec:contract v1 -> contract-spec.json 等"""
    if " " not in spec_type_version:
        return None
    part = spec_type_version.split()[0]  # spec:contract
    if ":" in part:
        name = part.split(":")[-1]  # contract
    else:
        name = part
    mapping = {
        "contract": "contract-spec.json",
        "modules": "modules-spec.json",
        "workflow": "workflow-spec.json",
        "adr": "adr-spec.json",
        "budgets": "budgets-spec.json",
    }
    fn = mapping.get(name)
    if not fn:
        return None
    return SCHEMAS / fn


def validate_version_matrix(matrix: dict, spec_type: str, version: str) -> bool:
    allowed = matrix.get("allowed") or {}
    versions = allowed.get(spec_type)
    if versions is None:
        return True  # 未限制則通過
    return version in versions


def main() -> int:
    if not GOVERNANCE.exists():
        print("ai-governance/ 不存在，跳過 schema 驗證。")
        return 0

    matrix_path = SCHEMAS / "version-matrix.yaml"
    if not matrix_path.exists():
        print("schemas/version-matrix.yaml 不存在。")
        return 1
    matrix = load_yaml(matrix_path)

    errors: list[str] = []

    # 1) contract.md 內 spec:contract v1
    contract_md = GOVERNANCE / "contract.md"
    if contract_md.exists():
        for type_ver, _, parsed in extract_spec_blocks(contract_md):
            if not type_ver.startswith("spec:contract"):
                continue
            v = type_ver.split()[-1] if " " in type_ver else ""
            if not validate_version_matrix(matrix, "contract", v):
                errors.append(f"contract: 版本 {v} 不在 version-matrix 允許清單")
            if parsed:
                schema_path = SCHEMAS / "contract-spec.json"
                if schema_path.exists():
                    validator = Draft202012Validator(load_json(schema_path))
                    for err in validator.iter_errors(parsed):
                        errors.append(f"contract.md spec block: {err.message}")

    # 2) modules.yaml
    modules_path = GOVERNANCE / "modules.yaml"
    if modules_path.exists():
        data = load_yaml(modules_path)
        # 略過第一行註解後再驗證（YAML 會把 # 行當註解）
        schema_path = SCHEMAS / "modules-spec.json"
        if schema_path.exists():
            validator = Draft202012Validator(load_json(schema_path))
            for err in validator.iter_errors(data):
                errors.append(f"modules.yaml: {err.message}")

    # 3) workflow.yaml
    workflow_path = GOVERNANCE / "workflow.yaml"
    if workflow_path.exists():
        data = load_yaml(workflow_path)
        schema_path = SCHEMAS / "workflow-spec.json"
        if schema_path.exists():
            validator = Draft202012Validator(load_json(schema_path))
            for err in validator.iter_errors(data):
                errors.append(f"workflow.yaml: {err.message}")

    # 4) budgets.yaml
    budgets_path = GOVERNANCE / "budgets.yaml"
    if budgets_path.exists():
        data = load_yaml(budgets_path)
        schema_path = SCHEMAS / "budgets-spec.json"
        if schema_path.exists():
            validator = Draft202012Validator(load_json(schema_path))
            for err in validator.iter_errors(data):
                errors.append(f"budgets.yaml: {err.message}")

    # 5) decisions/*.yaml (ADR)
    decisions_dir = GOVERNANCE / "decisions"
    if decisions_dir.exists():
        adr_schema = load_json(SCHEMAS / "adr-spec.json")
        validator = Draft202012Validator(adr_schema)
        for p in decisions_dir.glob("*.yaml"):
            data = load_yaml(p)
            if not data or "id" not in data:
                continue
            for err in validator.iter_errors(data):
                errors.append(f"decisions/{p.name}: {err.message}")

    # 6) change_log.jsonl 每一行（跳過 schema 說明行）
    change_log_path = GOVERNANCE / "change_log.jsonl"
    if change_log_path.exists():
        schema = load_json(SCHEMAS / "change-log-entry.json")
        validator = Draft202012Validator(schema)
        for i, line in enumerate(change_log_path.read_text(encoding="utf-8").strip().split("\n")):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append(f"change_log.jsonl line {i+1}: invalid JSON - {e}")
                continue
            if entry.get("_comment") and not entry.get("change_id"):
                continue  # schema 說明行
            for err in validator.iter_errors(entry):
                errors.append(f"change_log.jsonl line {i+1}: {err.message}")

    for e in errors:
        print(e, file=sys.stderr)
    if errors:
        return 1
    print("Schema 驗證通過。")

    # 若有 interop 目錄，一併驗證 AI ↔ AI 互通層
    interop_script = GOVERNANCE / "scripts" / "validate_interop.py"
    if (GOVERNANCE / "interop").exists() and interop_script.exists():
        import subprocess
        r = subprocess.run([sys.executable, str(interop_script)], cwd=REPO_ROOT)
        if r.returncode != 0:
            return r.returncode

    return 0


if __name__ == "__main__":
    sys.exit(main())
