#!/usr/bin/env python3
"""
AI ↔ AI 互通層驗證：interop 目錄下所有 YAML/JSON 依 schemas 機驗。
涵蓋原有六大基礎面向 + 新增七大突出模組（GaaP vs A2A）。
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

    # ── 新增七大突出模組驗證 (GaaP vs A2A) ────────────────────────────────

    # 7) capability-token-lifecycle.yaml -> capability-token.json
    #    只驗 spec 宣告區塊本身（lifecycle 規格 YAML 不帶 token 實例）
    cap_token_path = INTEROP / "capability-token-lifecycle.yaml"
    schema_path = SCHEMAS / "capability-token.json"
    if cap_token_path.exists() and schema_path.exists():
        data = load_yaml(cap_token_path)
        # 若 interop/tokens/ 目錄有 token 實例，逐一驗證
        tokens_dir = INTEROP / "tokens"
        if tokens_dir.exists():
            schema = load_json(schema_path)
            for p in tokens_dir.glob("*.yaml"):
                td = load_yaml(p)
                if td.get("spec") == "capability-token":
                    all_errors.extend(validate_one(td, schema, f"tokens/{p.name}"))

    # 8) consent-orchestration.yaml；interop/consents/ 下的 consent manifest 實例
    consent_dir = INTEROP / "consents"
    schema_path = SCHEMAS / "consent-manifest.json"
    if consent_dir.exists() and schema_path.exists():
        schema = load_json(schema_path)
        for p in consent_dir.glob("*.yaml"):
            data = load_yaml(p)
            if data.get("spec") == "consent-manifest":
                all_errors.extend(validate_one(data, schema, f"consents/{p.name}"))

    # 9) agent-reputation.yaml -> agent-reputation.json
    rep_path = INTEROP / "agent-reputation.yaml"
    schema_path = SCHEMAS / "agent-reputation.json"
    if rep_path.exists() and schema_path.exists():
        data = load_yaml(rep_path)
        example = data.get("example")
        if example and isinstance(example, dict):
            schema = load_json(schema_path)
            all_errors.extend(validate_one(example, schema, "agent-reputation.yaml#example"))
    # 若 interop/reputation/ 有 per-agent 記錄，逐一驗證
    rep_dir = INTEROP / "reputation"
    if rep_dir.exists():
        schema_path = SCHEMAS / "agent-reputation.json"
        if schema_path.exists():
            schema = load_json(schema_path)
            for p in rep_dir.glob("*.yaml"):
                data = load_yaml(p)
                if data.get("spec") == "agent-reputation":
                    all_errors.extend(validate_one(data, schema, f"reputation/{p.name}"))

    # 10) semantic-drift.yaml 下的 drift report 實例 -> semantic-drift-report.json
    drift_dir = INTEROP / "drift-reports"
    schema_path = SCHEMAS / "semantic-drift-report.json"
    if drift_dir.exists() and schema_path.exists():
        schema = load_json(schema_path)
        for p in drift_dir.glob("*.yaml"):
            data = load_yaml(p)
            if data.get("spec") == "semantic-drift-report":
                all_errors.extend(validate_one(data, schema, f"drift-reports/{p.name}"))

    # 11) rollback-coordination.yaml；interop/rollbacks/ 下的實例 -> rollback-plan.json
    rollback_dir = INTEROP / "rollbacks"
    schema_path = SCHEMAS / "rollback-plan.json"
    if rollback_dir.exists() and schema_path.exists():
        schema = load_json(schema_path)
        for p in rollback_dir.glob("*.yaml"):
            data = load_yaml(p)
            if data.get("spec") == "rollback-plan":
                all_errors.extend(validate_one(data, schema, f"rollbacks/{p.name}"))

    # 12) resource-governance.yaml；tasks/*.yaml 內的 resource_budget -> resource-budget.json
    schema_path = SCHEMAS / "resource-budget.json"
    if schema_path.exists():
        schema = load_json(schema_path)
        tasks_dir = INTEROP / "tasks"
        if tasks_dir.exists():
            for p in tasks_dir.glob("*.yaml"):
                data = load_yaml(p)
                budget = data.get("resource_budget")
                if budget and isinstance(budget, dict) and budget.get("spec") == "resource-budget":
                    all_errors.extend(validate_one(budget, schema, f"tasks/{p.name}#resource_budget"))
        # 若 interop/resource-budgets/ 有獨立檔案
        rb_dir = INTEROP / "resource-budgets"
        if rb_dir.exists():
            for p in rb_dir.glob("*.yaml"):
                data = load_yaml(p)
                if data.get("spec") == "resource-budget":
                    all_errors.extend(validate_one(data, schema, f"resource-budgets/{p.name}"))

    # 13) a2a-bridge.yaml；agent-card-extended -> agent-card-extended.json
    schema_path = SCHEMAS / "agent-card-extended.json"
    if schema_path.exists():
        schema = load_json(schema_path)
        cards_dir = INTEROP / "agent-cards"
        if cards_dir.exists():
            for p in cards_dir.glob("*.yaml"):
                data = load_yaml(p)
                if data.get("spec") == "agent-card-extended":
                    all_errors.extend(validate_one(data, schema, f"agent-cards/{p.name}"))
        # 驗證 agents/*.yaml 若有 spec=agent-card-extended
        agents_dir = INTEROP / "agents"
        if agents_dir.exists():
            for p in agents_dir.glob("*.yaml"):
                data = load_yaml(p)
                if data.get("spec") == "agent-card-extended":
                    all_errors.extend(validate_one(data, schema, f"agents/{p.name}"))

    # ── 驗證結果輸出 ──────────────────────────────────────────────────────

    for e in all_errors:
        print(e, file=sys.stderr)
    if all_errors:
        return 1
    print("Interop 驗證通過（含七大 GaaP 突出模組）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())