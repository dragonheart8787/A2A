# System Contract（系統契約）

> **用途**：定義此專案「是什麼 / 不是什麼」與不可侵犯原則。  
> AI 必須在每次變更前讀取並遵守本契約。

---

## Spec Block: Contract

```yaml
# spec:contract v1
project: "[PROJECT_NAME]"   # 替換為實際專案名稱
version: "1.0.0"

scope:
  in:
    - "[專案範圍內項目 1]"
    - "[專案範圍內項目 2]"
  out:
    - "[明確排除項目 1，例如：rewrite GUI framework]"
    - "[明確排除項目 2，例如：replace database layer]"

invariants:
  - id: INV-API-001
    rule: "Public API signatures under 約定路徑 不得變更；僅允許 minor/patch。"
  - id: INV-MOD-002
    rule: "標記為 stable 的模組不得重寫；僅允許 patch-level 編輯（bugfix/perf）。"
  - id: INV-DEP-003
    rule: "新增依賴必須經 Allowlist 審核並寫入 dependency allowlist。"
  - id: INV-BREAK-004
    rule: "Breaking change 必須附 rollback_plan、影響面清單與 semver major bump。"

gates_required: true
workflow_required: true
change_log_required: true
```

---

## 決策閘門（Gates）— 強制邏輯

AI 在動手寫碼前**必須**產出可檢查的結構化輸出，通過下列閘門。

### Gate 1：Reuse-first（先重用）

| 輸出項 | 說明 |
|--------|------|
| target_files | 要改的檔案 / 模組清單 |
| equivalent_exists | 是否已有等價能力（true/false） |
| reuse_justification | 若 equivalent_exists=true 仍要改：列出 2–3 點具體限制 |

```yaml
# spec:gate-reuse v1
gate: reuse_first
output_schema:
  target_files: [string]
  equivalent_exists: boolean
  reuse_justification: string | null
```

### Gate 2：Diff-only（差異優先）

整檔重寫僅在以下條件**全部**滿足時允許：

- risk: low
- test_coverage: ">= 80%"
- module_stability: beta | experimental
- impact: 不觸動 public API

```yaml
# spec:gate-diff v1
gate: diff_only
full_rewrite_allowed_when:
  risk: low
  test_coverage_min: 80
  module_stability: [beta, experimental]
  public_api_unchanged: true
```

### Gate 3：Complexity Budget（複雜度預算）

每次改動必須符合 `budgets.yaml` 定義之預算（見同目錄）。

- 新增檔案數上限
- 新增依賴上限
- 新增 public functions 上限
- Cyclomatic complexity 不得無故上升（或僅 +N，由 budget 定義）

### Gate 4：Evidence-based（憑證驅動）

「需要重寫」之主張必須附：

- 目前 bug / performance bottleneck 的定位
- benchmark 或 profiler 結果（可為連結或摘要）
- failing tests / logs 引用

```yaml
# spec:gate-evidence v1
gate: evidence_based
required_for_rewrite:
  - bug_location_or_perf_bottleneck
  - benchmark_or_profiler_result
  - failing_tests_or_logs_ref
```

---

## 身份與版本規則

- **Spec 區塊**：每個區塊標註 `type + version`（如 `spec:contract v1`）。
- **模組穩定度**：`experimental` | `beta` | `stable` | `deprecated`。
- **API Semver**：major = breaking；minor = 向後相容新功能；patch = bugfix/內部改動。

---

## 依賴與邊界

- **allowed_imports**：禁止跨層引用（由 `architecture.md` / `modules.yaml` 定義層級）。
- **dependency_allowlist**：新增依賴必須寫入 allowlist 並標註審核狀態。

---

*AI 解讀本文件時，僅能依照上述 YAML schema 區塊解讀，不得自由延伸或忽略 invariants / gates。*
