#!/usr/bin/env python3
"""
Enforcement hooks：5 條 MVP 校驗。
- 有程式變更必須新增 change_log.jsonl 一筆
- touched_files 與 git diff 一致
- 觸及 stability:stable 模組禁止大改（>N 行）
- 新增依賴必須在 allowlist
- breaking 必須附 rollback_plan

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

    for e in errors:
        print(e, file=sys.stderr)
    if errors:
        return 1
    print("Enforcement 通過。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
