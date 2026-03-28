#!/usr/bin/env python3
"""
Enforcement hooks：7 條 MVP 校驗。
- 有程式變更必須新增 change_log.jsonl 一筆
- touched_files 與 git diff 一致
- 觸及 stability:stable 模組禁止大改（>N 行）
- 新增依賴必須在 allowlist
- breaking 必須附 rollback_plan
- [MVP 6] resource_budget 若存在，actual_usage 不得超出 limits
- [MVP 7] 含敏感操作的 task，delivery_envelope 必須有 consent_grant_ref

使用方式：
  pre-commit:  python enforce.py
  CI:          GOVERNANCE_CI_BASE=main python enforce.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, ValidationError

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GOVERNANCE = REPO_ROOT / "ai-governance"
SCHEMAS = GOVERNANCE / "schemas"

# 不計入「程式變更」的路徑前綴（這些變更不強制要求 change_log）
EXCLUDE_PATHS = ("ai-governance/", ".cursor/", ".github/")

# 依賴檔：用來偵測新增依賴
DEP_FILES = [
    "package.json",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "go.mod",
]


def run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=cwd or REPO_ROOT, capture_output=True, text=True, encoding="utf-8")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def get_changed_files(is_ci: bool) -> list[str]:
    if is_ci:
        base = os.environ.get("GOVERNANCE_CI_BASE", "HEAD^")
        code, out = run(["git", "diff", "--name-only", base, "HEAD"])
    else:
        code, out = run(["git", "diff", "--cached", "--name-only"])
    if code != 0:
        return []
    return [f.strip() for f in out.strip().split("\n") if f.strip()]


def is_code_change(path: str) -> bool:
    return not any(path.startswith(p) for p in EXCLUDE_PATHS)


def get_change_log_new_entries() -> list[dict]:
    """比對 base 與目前工作區的 change_log.jsonl，回傳新增的 entry。CI 時用 GOVERNANCE_CI_BASE。"""
    log_path = GOVERNANCE / "change_log.jsonl"
    if not log_path.exists():
        return []
    current_lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    base_ref = os.environ.get("GOVERNANCE_CI_BASE", "HEAD")
    code, base_content = run(["git", "show", f"{base_ref}:ai-governance/change_log.jsonl"])
    if code != 0:
        base_lines = []
    else:
        base_lines = base_content.strip().split("\n") if base_content.strip() else []
    base_set = set(line.strip() for line in base_lines if line.strip() and not line.strip().startswith("#"))
    new_entries = []
    for line in current_lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line in base_set:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("_comment") and not entry.get("change_id"):
            continue
        new_entries.append(entry)
    return new_entries


def get_diff_numstat(files: list[str], is_ci: bool) -> dict[str, int]:
    """回傳每個檔案的總變更行數（added + deleted）。"""
    if is_ci:
        base = os.environ.get("GOVERNANCE_CI_BASE", "HEAD^")
        code, out = run(["git", "diff", "--numstat", base, "HEAD", "--"] + files)
    else:
        code, out = run(["git", "diff", "--cached", "--numstat", "--"] + files)
    result = {}
    for line in out.strip().split("\n"):
        if not line:
            continue
        parts = line.split(None, 2)
        if len(parts) >= 2:
            try:
                add = int(parts[0]) if parts[0] != "-" else 0
                remove = int(parts[1]) if parts[1] != "-" else 0
                result[parts[2]] = add + remove
            except (ValueError, IndexError):
                pass
    return result


def get_stable_module_paths() -> list[str]:
    """modules.yaml 中 stability: stable 的 path 列表（用於前綴比對）。"""
    modules_path = GOVERNANCE / "modules.yaml"
    if not modules_path.exists():
        return []
    data = yaml.safe_load(modules_path.read_text(encoding="utf-8")) or {}
    paths = []
    for m in data.get("modules") or []:
        if m.get("stability") == "stable" and m.get("path"):
            p = m.get("path", "").rstrip("/")
            if p:
                paths.append(p + "/")
    return paths


def get_stable_max_lines() -> int:
    budgets_path = GOVERNANCE / "budgets.yaml"
    if not budgets_path.exists():
        return 50
    data = yaml.safe_load(budgets_path.read_text(encoding="utf-8")) or {}
    limits = data.get("per_change_limits") or {}
    return int(limits.get("stable_module_max_diff_lines", 50))


def get_dependency_allowlist() -> list[str]:
    """已核准的依賴名稱（小寫、去版本號）。"""
    modules_path = GOVERNANCE / "modules.yaml"
    if not modules_path.exists():
        return []
    data = yaml.safe_load(modules_path.read_text(encoding="utf-8")) or {}
    allowlist = data.get("dependency_allowlist") or []
    names = []
    for item in allowlist:
        if isinstance(item, dict) and item.get("approved") is True and item.get("name"):
            names.append(item["name"].lower())
        elif isinstance(item, str):
            names.append(item.lower())
    return names


def detect_new_dependencies() -> list[str]:
    """比對 base 與 HEAD 的依賴檔，回傳新增的套件名。"""
    is_ci = "GOVERNANCE_CI_BASE" in os.environ
    base = os.environ.get("GOVERNANCE_CI_BASE", "HEAD^") if is_ci else "HEAD"
    new_deps = []
    for dep_file in DEP_FILES:
        path = REPO_ROOT / dep_file
        if not path.exists():
            continue
        code, old_content = run(["git", "show", f"{base}:{dep_file}"])
        old_content = old_content if code == 0 else ""
        new_content = path.read_text(encoding="utf-8")
        if old_content == new_content:
            continue
        # 簡易解析：package.json -> dependencies keys; requirements.txt -> 包名
        if dep_file == "package.json":
            try:
                old_j = json.loads(old_content) if old_content else {}
                new_j = json.loads(new_content)
                old_deps = set((old_j.get("dependencies") or {}).keys()) | set((old_j.get("devDependencies") or {}).keys())
                new_deps_set = set((new_j.get("dependencies") or {}).keys()) | set((new_j.get("devDependencies") or {}).keys())
                for name in new_deps_set - old_deps:
                    new_deps.append(name.lower())
            except json.JSONDecodeError:
                pass
        elif dep_file in ("requirements.txt", "requirements-dev.txt"):
            def parse_req(c: str) -> set:
                s = set()
                for line in c.split("\n"):
                    line = line.split("#")[0].strip()
                    if line and not line.startswith("-"):
                        pkg = line.split("==")[0].split(">=")[0].split("[")[0].strip().lower()
                        if pkg:
                            s.add(pkg)
                return s
            new_deps.extend(parse_req(new_content) - parse_req(old_content))
    return new_deps


def main() -> int:
    if not GOVERNANCE.exists():
        return 0

    is_ci = "GOVERNANCE_CI_BASE" in os.environ
    changed = get_changed_files(is_ci)
    code_changes = [f for f in changed if is_code_change(f)]

    errors: list[str] = []

    # 若沒有程式變更，只做 schema 與 change_log 單行格式檢查（可選：跳過強制）
    if not code_changes:
        # 仍可檢查：若有改 change_log.jsonl，新行格式要對
        new_entries = get_change_log_new_entries()
        schema_path = SCHEMAS / "change-log-entry.json"
        if schema_path.exists() and new_entries:
            validator = Draft202012Validator(json.loads(schema_path.read_text()))
            for i, entry in enumerate(new_entries):
                for err in validator.iter_errors(entry):
                    errors.append(f"change_log 新筆 {i+1}: {err.message}")
        if errors:
            for e in errors:
                print(e, file=sys.stderr)
            return 1
        return 0

    # MVP 1: 所有變更必須新增一筆 change_log.jsonl
    new_entries = get_change_log_new_entries()
    if not new_entries:
        errors.append("ENFORCE: 有程式變更但未在 ai-governance/change_log.jsonl 新增任何一筆記錄。")

    # change_log entry schema 驗證
    schema_path = SCHEMAS / "change-log-entry.json"
    if schema_path.exists():
        validator = Draft202012Validator(json.loads(schema_path.read_text()))
        for i, entry in enumerate(new_entries):
            for err in validator.iter_errors(entry):
                errors.append(f"change_log 新筆 {i+1}: {err.message}")

    # MVP 2: touched_files 必須與 git diff 一致
    if new_entries:
        logged = set()
        for e in new_entries:
            logged.update(e.get("touched_files") or [])
        diff_set = set(code_changes)
        if logged != diff_set:
            missing = diff_set - logged
            extra = logged - diff_set
            if missing:
                errors.append(f"ENFORCE: touched_files 未包含下列實際變更檔案: {sorted(missing)}")
            if extra:
                errors.append(f"ENFORCE: touched_files 列出但未變更的檔案: {sorted(extra)}")

    # MVP 3: 觸及 stable 模組禁止大改
    stable_paths = get_stable_module_paths()
    max_lines = get_stable_max_lines()
    if stable_paths:
        numstat = get_diff_numstat(code_changes, is_ci)
        for path, total in numstat.items():
            if any(path.startswith(p) or path.replace("\\", "/").startswith(p) for p in stable_paths):
                if total > max_lines:
                    errors.append(f"ENFORCE: 檔案 {path} 屬於 stability:stable 模組，單檔變更 {total} 行超過上限 {max_lines}。")

    # MVP 4: 新增依賴必須在 allowlist
    allowlist = get_dependency_allowlist()
    new_deps = detect_new_dependencies()
    for dep in new_deps:
        if dep not in allowlist:
            errors.append(f"ENFORCE: 新增依賴 '{dep}' 未在 modules.yaml dependency_allowlist 中核准。")

    # MVP 5: breaking 必須標註且附 rollback_plan
    for i, entry in enumerate(new_entries):
        if entry.get("breaking") is True:
            rp = entry.get("rollback_plan") or ""
            if not str(rp).strip():
                errors.append(f"ENFORCE: change_log 新筆 {i+1} 為 breaking change，但未填 rollback_plan。")

    # MVP 6: resource_budget — actual_usage 不得超出 limits
    errors.extend(_check_resource_budgets())

    # MVP 7: consent gate — 含敏感操作的 task 交付必須附 consent_grant_ref
    errors.extend(_check_consent_gates())

    for e in errors:
        print(e, file=sys.stderr)
    if errors:
        return 1
    print("Enforcement 通過。")
    return 0


# ---------------------------------------------------------------------------
# MVP 6: Resource Budget 校驗
# ---------------------------------------------------------------------------

SENSITIVE_OPERATIONS = {
    "read_sensitive_data", "write_sensitive_data", "delete_data",
    "external_api_call", "credential_access", "payment_operation",
    "identity_verification", "cross_agent_data_share",
    "file_system_write", "code_execution",
}


def _load_interop_yaml(filename: str) -> dict:
    path = GOVERNANCE / "interop" / filename
    if not path.exists():
        return {}
    try:
        import yaml as _yaml
        return _yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _check_resource_budgets() -> list[str]:
    """MVP 6：掃描 interop/tasks/*.yaml，若帶 resource_budget，驗證 actual_usage 不超 limits。"""
    errors: list[str] = []
    tasks_dir = GOVERNANCE / "interop" / "tasks"
    if not tasks_dir.exists():
        return errors
    schema_path = GOVERNANCE / "interop" / "schemas" / "resource-budget.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8")) if schema_path.exists() else None

    import yaml as _yaml
    for p in tasks_dir.glob("*.yaml"):
        try:
            data = _yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        budget = data.get("resource_budget")
        if not budget:
            continue
        if schema:
            validator = Draft202012Validator(schema)
            for err in validator.iter_errors(budget):
                errors.append(f"ENFORCE [MVP6]: tasks/{p.name} resource_budget schema 錯誤: {err.message}")
        limits = budget.get("limits") or {}
        actual = budget.get("actual_usage") or {}
        checks = [
            ("token_cost_ceiling", "token_cost_actual"),
            ("compute_budget_seconds", "compute_seconds_used"),
            ("tool_calls_max", "tool_calls_used"),
            ("output_tokens_max", "output_tokens_used"),
            ("network_requests_max", "network_requests_used"),
        ]
        for limit_key, actual_key in checks:
            limit_val = limits.get(limit_key)
            actual_val = actual.get(actual_key)
            if limit_val is not None and actual_val is not None:
                if actual_val > limit_val:
                    errors.append(
                        f"ENFORCE [MVP6]: tasks/{p.name} 超出 resource_budget.limits.{limit_key}："
                        f" actual={actual_val} > limit={limit_val}。"
                        f" 請拆分工單或申請 budget 豁免。"
                    )
    return errors


def _check_consent_gates() -> list[str]:
    """MVP 7：掃描 interop/tasks/*.yaml，含敏感操作時必須附 consent_grant_ref。"""
    errors: list[str] = []
    tasks_dir = GOVERNANCE / "interop" / "tasks"
    if not tasks_dir.exists():
        return errors
    import yaml as _yaml
    for p in tasks_dir.glob("*.yaml"):
        try:
            data = _yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        operations = data.get("sensitive_operations") or []
        if not operations:
            constraints = data.get("constraints") or {}
            operations = constraints.get("sensitive_operations") or []
        if not operations:
            continue
        has_sensitive = any(op in SENSITIVE_OPERATIONS for op in operations)
        if not has_sensitive:
            continue
        delivery = data.get("delivery_envelope") or {}
        consent_ref = delivery.get("consent_grant_ref") or data.get("consent_grant_ref")
        if not consent_ref:
            errors.append(
                f"ENFORCE [MVP7]: tasks/{p.name} 包含敏感操作 {operations}，"
                f" 但 delivery_envelope 缺少 consent_grant_ref。"
                f" 請先完成 consent-orchestration 並填入 consent_grant_ref。"
            )
    return errors


if __name__ == "__main__":
    sys.exit(main())
