# System Contract（系統契約）

> **用途**：定義此專案「是什麼 / 不是什麼」與不可侵犯原則。  
> AI 必須在每次變更前讀取並遵守本契約。

---

## Spec Block: Contract

```yaml
# spec:contract v1
project: "GaaP — Governance-as-a-Protocol"
version: "2.0.0"

scope:
  in:
    - "GaaP 執行期函式庫（gaap_runtime.py）：七大模組的 Python 實作"
    - "A2A-compatible Agent Server / Client（examples/agent_server.py、agent_client.py）"
    - "AI 治理規格（ai-governance/）：契約、架構、模組、工作流程、預算"
    - "AI↔AI 互通協定（interop/）：身份、工單、工件、協作、安全、七大 GaaP 模組"
    - "CI / pre-commit 硬治理（enforce.py 七條 MVP）"
    - "JSON Schema 機驗層（schemas/、interop/schemas/）"
  out:
    - "生產環境 LLM API 封裝（非本 repo 範疇，屬上層應用）"
    - "使用者介面 / Dashboard（治理層不提供 UI）"
    - "特定 LLM 廠商 SDK 整合（框架無關；呼叫者自行橋接）"
    - "資料庫儲存層（token registry、consent log 預設 in-memory；持久化由部署層決定）"

invariants:
  - id: INV-API-001
    rule: "gaap_runtime.py 的 GaaPGateway.authorize_execute 與 verify_delivery 簽名不得破壞相容性；僅允許向後相容的參數新增（keyword-only，有預設值）。"
  - id: INV-MOD-002
    rule: "標記為 stability: stable 的模組（gaap_runtime、enforce、validate_schemas）不得整檔重寫；僅允許 patch-level 編輯（bugfix / perf）。"
  - id: INV-DEP-003
    rule: "核心執行期（gaap_runtime.py、demo_full_flow.py、agent_server.py、agent_client.py）不得新增超出 Python stdlib 的依賴；驗證層（enforce.py、validate_*.py）僅允許 pyyaml、jsonschema。"
  - id: INV-BREAK-004
    rule: "Breaking change 必須附 rollback_plan、影響面清單與 semver major bump。"
  - id: INV-SCHEMA-005
    rule: "所有 interop/schemas/*.json 的 required 欄位不得移除；只能新增可選欄位（additionalProperties: true）。"
  - id: INV-DRIFT-006
    rule: "SemanticDriftDetector.AUTO_REJECT_THRESHOLD（0.40）不得在未附 evidence 的情況下調高；調高視為 breaking change。"

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
- impact: 不觸動 GaaPGateway public API

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

每次改動必須符合 `budgets.yaml` 定義之預算：

- 新增檔案數上限：3
- 新增依賴上限：0（核心）/ 1（驗證層）
- 新增 public functions 上限：5
- Cyclomatic complexity delta：≤ +2

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
- **執行期版本**：`gaap_runtime.py` 版本對應 `GaaPGateway` API 版本，見 `architecture.md`。

---

## 依賴與邊界

- **核心執行期依賴**：Python stdlib only（hashlib、uuid、time、dataclasses、http.server）
- **驗證層依賴**：pyyaml >= 6.0、jsonschema >= 4.0
- **dependency_allowlist**：見 `modules.yaml`；新增依賴必須先登記並標註 approved: true

---

*AI 解讀本文件時，僅能依照上述 YAML schema 區塊解讀，不得自由延伸或忽略 invariants / gates。*
