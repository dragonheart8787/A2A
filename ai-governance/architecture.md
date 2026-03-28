# Architecture + API Canon（架構與 API 正典）

> **用途**：讓 AI 知道模組邊界、public interfaces、data schema，避免重寫「不可動的公共面」。  
> 本檔對應 GaaP v2.0.0 的實際實作（`examples/gaap_runtime.py`、`examples/agent_server.py`）。

---

## Spec Block: Architecture Overview

```yaml
# spec:architecture v1
layers:
  - name: runtime
    description: "GaaP 執行期治理函式庫（gaap_runtime.py）；七大模組的真實 Python 實作"
    modules: [gaap_runtime]
  - name: api
    description: "A2A-compatible Agent Server / Client（agent_server.py、agent_client.py）"
    modules: [agent_server, agent_client]
  - name: demo
    description: "端到端 Demo 與 sample output（demo_full_flow.py、sample_output.txt）"
    modules: [demo_full_flow]
  - name: ci
    description: "CI / pre-commit 驗證與 enforcement（enforce.py、validate_*.py）"
    modules: [enforce, validate_schemas, validate_interop]
  - name: spec
    description: "治理規格（ai-governance/）與 AI↔AI 互通協定（interop/）"
    modules: [interop_specs, governance_docs]

module_boundaries:
  rule: "runtime ← api ← demo；ci 獨立執行，不 import runtime；spec 為靜態文件層"
  dependency_direction: "上層可 import 下層，下層不得 import 上層（stdlib 除外）"
```

---

## Public Interfaces（GaaP Runtime API Canon）

以下為 `examples/gaap_runtime.py` 的公開介面。簽名變更視為 breaking change（INV-API-001）。

```yaml
# spec:api-canon v1
apis:
  - module: gaap_runtime
    classes:
      - class: GaaPGateway
        description: "統一 GaaP 治理閘道；整合七大模組，依序執行所有檢查"
        methods:
          - signature: "authorize_execute(*, token_id, work_contract_id, requested_capability, agent_id, operation_type, consent_grant_ref, budget_id, policy_context, required_trust_tier='standard') -> tuple[bool, list[GaaPResult]]"
            description: "執行前授權（Policy + Token + Trust + Consent + Resource 五層並發）"
            errors:
              - "returns (False, results) if any module fails; never raises"
          - signature: "verify_delivery(*, objective, objective_keywords, deliverable_summary, metric_thresholds, actual_metrics, forbidden_changes_detected) -> tuple[bool, GaaPResult]"
            description: "交付前語意漂移偵測（SemanticDriftDetector）"

      - class: EphemeralTokenRegistry
        methods:
          - signature: "issue(agent_id, work_contract_id, scoped_capabilities, ttl_seconds=300, task_id=None) -> CapabilityToken"
          - signature: "revoke(token_id, reason='') -> None"
          - signature: "get(token_id) -> CapabilityToken | None"

      - class: ConsentGate
        methods:
          - signature: "request_consent(operation_type, sensitive_fields, task_id) -> ConsentRecord"
          - signature: "grant(consent_id, granted_by='human') -> None"
          - signature: "deny(consent_id) -> None"
          - signature: "check(operation_type, consent_grant_ref) -> GaaPResult"

      - class: TrustScoreEngine
        methods:
          - signature: "record_event(agent_id, event) -> None"
            notes: "event: task_completed | task_failed | policy_violation | drift_incident | consent_violation | rollback_triggered"
          - signature: "check_capability(agent_id, required_tier='standard') -> GaaPResult"
            notes: "tier: full(>=0.8) | standard(>=0.6) | restricted(>=0.4) | sandbox_only(<0.4)"

      - class: SemanticDriftDetector
        methods:
          - signature: "detect(objective, objective_keywords, deliverable_summary, metric_thresholds=None, actual_metrics=None, forbidden_changes_detected=False) -> GaaPResult"
            notes: "drift_score: 0.0=完全對齊, 1.0=完全偏離; auto_reject > 0.40"

      - class: ResourceGuard
        methods:
          - signature: "create_budget(task_id, token_cost_ceiling=2.0, compute_budget_seconds=300, tool_calls_max=50, overflow_action='terminate') -> ResourceBudget"
          - signature: "record_usage(budget_id, token_cost=0.0, compute_seconds=0, tool_calls=0) -> None"
          - signature: "check(budget_id) -> GaaPResult"

      - class: RollbackCoordinator
        methods:
          - signature: "register_snapshot(agent_id, snapshot_ref) -> None"
          - signature: "initiate(work_contract_id, trigger, affected_agents, strategy='partial_rollback') -> RollbackPlan"
          - signature: "execute(rollback_id) -> GaaPResult"

      - class: PolicyGate
        methods:
          - signature: "PolicyGate(contract_hash, invariants=None)"
          - signature: "check(policy_context) -> GaaPResult"

    dataclasses:
      - name: GaaPResult
        fields: [passed, module, message, details]
        immutable: true
      - name: CapabilityToken
        fields: [token_id, agent_id, work_contract_id, scoped_capabilities, issued_at, expires_at, revoked, task_id]
      - name: ConsentRecord
        fields: [consent_id, operation_type, sensitive_fields, status, granted_by, granted_at]
      - name: ResourceBudget
        fields: [budget_id, task_id, token_cost_ceiling, compute_budget_seconds, tool_calls_max, overflow_action, token_cost_actual, compute_seconds_used, tool_calls_used]
```

---

## A2A Bridge Layer API（agent_server.py）

```yaml
# spec:api-canon v1
apis:
  - module: agent_server
    endpoints:
      - path: "GET /.well-known/agent-card.json"
        description: "Extended Agent Card（A2A-compatible + GaaP governance metadata）"
        response_schema: "interop/schemas/agent-card-extended.json"
        notes: "同時支援 /.well-known/agent.json（舊路徑，A2A SDK < v0.3.x 相容）"

      - path: "GET /.well-known/agent.json"
        description: "舊版 A2A discovery 路徑（backward compatibility）；回傳同 agent-card.json"
        notes: "A2A SDK v0.3.x 後官方路徑已改為 agent-card.json；本 server 同時支援兩者"

      - path: "POST /tasks/send"
        description: "JSON-RPC 2.0 任務接收（A2A 標準格式 + gaap_meta 解析）"
        request_schema:
          jsonrpc: "2.0"
          method: "tasks/send"
          params:
            capability_id: "string"
            parameters: "object"
            gaap_meta: "object（可選；缺少則 A2A-only 模式）"
        response_schema:
          on_pass: "{ result: { status, task_id, output, artifact_hash, gaap_result } }"
          on_fail: "{ error: { code: -32001, message, data: governance_report } }"
          on_a2a_only: "{ result: { status: accepted, warning: No GaaP governance applied } }"

      - path: "GET /health"
        description: "健康檢查 + demo token/consent ID"

      - path: "GET /demo-credentials"
        description: "取得 demo 用 token_id、consent_id（供 agent_client.py 使用）"
```

---

## Data Schema（JSON Schema 路徑索引）

```yaml
# spec:data-schema v1
schemas:
  - name: "capability-token"
    format: json
    path_or_ref: "ai-governance/interop/schemas/capability-token.json"
    mutable: false

  - name: "consent-manifest"
    format: json
    path_or_ref: "ai-governance/interop/schemas/consent-manifest.json"
    mutable: false

  - name: "agent-reputation"
    format: json
    path_or_ref: "ai-governance/interop/schemas/agent-reputation.json"
    mutable: false

  - name: "semantic-drift-report"
    format: json
    path_or_ref: "ai-governance/interop/schemas/semantic-drift-report.json"
    mutable: false

  - name: "rollback-plan"
    format: json
    path_or_ref: "ai-governance/interop/schemas/rollback-plan.json"
    mutable: false

  - name: "resource-budget"
    format: json
    path_or_ref: "ai-governance/interop/schemas/resource-budget.json"
    mutable: false

  - name: "agent-card-extended"
    format: json
    path_or_ref: "ai-governance/interop/schemas/agent-card-extended.json"
    mutable: false

  - name: "task-ticket"
    format: json
    path_or_ref: "ai-governance/interop/schemas/task-ticket.json"
    mutable: false

  - name: "change-log-entry"
    format: json
    path_or_ref: "ai-governance/schemas/change-log-entry.json"
    mutable: false
```

---

## 關鍵設計決策（ADR 索引）

| ADR | 決策 | 狀態 |
|---|---|---|
| ADR-0001 | 採用 Markdown 內嵌 YAML spec block 作為機讀契約格式 | accepted |
| ADR-0002 | GaaP 執行期採用 Python stdlib only（零額外依賴） | accepted |

---

*AI 重寫前必須檢查：目標是否為上述 public 介面或 schema；若是，僅允許不破壞相容性的 patch。*
