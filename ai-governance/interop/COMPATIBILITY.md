# A2A Compatibility Layer — GaaP Bridge

**定位**：不是取代 A2A，而是「吞掉它」——協議的 transport / discovery **兼容 A2A**，在上層加上完整的 **GaaP（Governance-as-a-Protocol）治理層**。

> **"A2A-compatible, enterprise-grade Governance-as-a-Protocol"**

---

## 兼容策略

A2A 是通訊標準。本系統是執行治理標準。兩者在不同層次工作，可以疊加：

```
┌─────────────────────────────────────────────────┐
│         GaaP 治理層（本系統新增）                 │
│  Token | Consent | Reputation | Drift | Rollback │
│  Resource Budget | Policy-as-Code | WorkContract │
├─────────────────────────────────────────────────┤
│         A2A 通訊層（保留完整）                   │
│  Agent Card | tasks/send | SSE | JSON-RPC 2.0   │
└─────────────────────────────────────────────────┘
```

---

## A2A Agent Card → agent-card-extended 欄位映射

| A2A 標準欄位 | GaaP 對應 | 備注 |
|---|---|---|
| `name` | `name` | 完整保留 |
| `description` | `description` | 完整保留 |
| `version` | `version` | 完整保留 |
| `contact` | `contact` | 完整保留 |
| `endpoints.tasks` | `endpoints.tasks` | 完整保留 |
| `endpoints.stream` | `endpoints.stream` | 完整保留 |
| `auth.type` (oauth2/api_key/jwt) | `auth.type` | 擴充：新增 `capability_token` 類型 |
| `capabilities[].id` | `capabilities[].id` | 完整保留 |
| `capabilities[].name` | `capabilities[].name` | 完整保留 |
| `capabilities[].parameters` | `capabilities[].parameters` | 完整保留 |
| `capabilities[].returns` | `capabilities[].returns` | 完整保留 |
| **（無）** | `capabilities[].requires_consent` | **GaaP 新增**：此能力是否需 consent_gate |
| **（無）** | `capabilities[].min_trust_score` | **GaaP 新增**：最低 trust_score 要求 |
| **（無）** | `gaap_governance.reputation` | **GaaP 新增**：信任評分摘要 |
| **（無）** | `gaap_governance.consent_requirements` | **GaaP 新增**：需要 consent 的操作類型 |
| **（無）** | `gaap_governance.resource_limits` | **GaaP 新增**：預設資源上限 |
| **（無）** | `gaap_governance.token_policy` | **GaaP 新增**：Capability Token 政策 |
| **（無）** | `gaap_governance.no_rewrite_semantics` | **GaaP 新增**：預設 change_mode |

Schema：[schemas/agent-card-extended.json](schemas/agent-card-extended.json)

---

## A2A JSON-RPC Message → GaaP gaap_meta 注入

### 原始 A2A 請求

```json
{
  "jsonrpc": "2.0",
  "method": "tasks/send",
  "params": {
    "capability_id": "backend_impl",
    "parameters": { "task_id": "TASK-001" }
  },
  "id": "req-123"
}
```

### 注入 GaaP 治理元數據後

```json
{
  "jsonrpc": "2.0",
  "method": "tasks/send",
  "params": {
    "capability_id": "backend_impl",
    "parameters": { "task_id": "TASK-001" },
    "gaap_meta": {
      "work_contract_id": "WC-2025-001",
      "capability_token_id": "tok-abc123",
      "policy_context": {
        "contract_hash": "sha256:deadbeef...",
        "modules_hash": "sha256:cafebabe..."
      },
      "trace_id": "trace-xyz-789",
      "span_id": "span-001",
      "consent_grant_ref": "consent-456",
      "resource_budget_ref": "budget-task001"
    }
  },
  "id": "req-123"
}
```

**注意**：非 GaaP 端自動略過 `gaap_meta`（JSON-RPC 允許額外欄位）；不破壞相容性。

---

## A2A Task States → GaaP Coordination Protocol 對應

| A2A 狀態 | GaaP 狀態 | 說明 |
|---|---|---|
| Created | propose | Owner 發出 task ticket |
| Working | execute | Consumer 執行中（需已通過 policy gate + consent gate） |
| NeedsInput | review（accept_with_needs） | Consumer 請求補充 inputs |
| Completed | verify | 須先通過語意漂移偵測才能進入此狀態 |
| Failed | close_fail | 可觸發 rollback-coordination |
| Canceled | close（human_requested rollback） | 觸發 rollback-coordination |

---

## A2A Response → GaaP 驗收結果擴充

```json
{
  "jsonrpc": "2.0",
  "result": {
    "converted_amount": 92.45,
    "rate": 0.9245
  },
  "gaap_result": {
    "policy_check_result": { "pass": true, "violated_rules": [] },
    "semantic_drift_report_ref": "drift-report-001",
    "delivery_envelope_ref": "env-artifact-001",
    "consent_grant_ref": "consent-456",
    "agent_trust_score_after": 0.84
  },
  "id": "req-123"
}
```

---

## Discovery 相容

A2A 使用 `/.well-known/agent.json` 作為 Agent Card discovery 端點。

本系統的 agent-card-extended 可直接部署在同一路徑：

- A2A-aware 端：讀取標準 A2A 欄位（name/capabilities/endpoints/auth）
- GaaP-aware 端：額外讀取 `gaap_governance` 欄位
- 兩者共存，無需維護兩份文件

---

## 遷移路徑

| 遷移階段 | 動作 | 效果 |
|---|---|---|
| **Phase 0（現有 A2A）** | 不動 | 維持 A2A 通訊功能 |
| **Phase 1（Agent Card 升級）** | 替換 agent.json 為 agent-card-extended | 新增 reputation/consent/resource 元數據 |
| **Phase 2（message 注入）** | 在 tasks/send params 加入 gaap_meta | 啟用 token + policy + consent + observability |
| **Phase 3（驗收升級）** | 交付帶 delivery_envelope；跑語意漂移偵測 | 完整 GaaP 執行治理啟用 |

---

## 合作框架相容性

| A2A 生態系框架 | 橋接方式 |
|---|---|
| **LangGraph** | 在 `langgraph.a2a` module 的 message handler 注入 `gaap_meta` |
| **CrewAI** | 包裝 `crewai-a2a` adapter，在 task 送出前附加 GaaP 欄位 |
| **Google ADK** | 在 ADK A2A client 的 request builder 加入 gaap_meta middleware |
| **Semantic Kernel** | 在 `Microsoft.SemanticKernel.A2A` plugin 加入 GaaP response handler |

詳細橋接實作見 [a2a-bridge.yaml](a2a-bridge.yaml)。
