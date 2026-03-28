# Governance-as-a-Protocol（GaaP）vs. Google A2A

> **定位**：本系統不是 A2A 的替代品，而是「A2A-compatible + 企業級執行治理」。  
> Google A2A 是通訊協定；GaaP 是治理協定。兩者互補，GaaP 吞掉 A2A 並在上層疊加。

---

## 一句話差異

| | Google A2A | 本系統（GaaP） |
|---|---|---|
| **本質** | Agent 通訊協定（怎麼說話） | Governance-as-a-Protocol（怎麼做事） |
| **核心問題** | 「Agent 之間如何傳遞訊息？」 | 「Agent 如何在有治理的情況下協作？」 |

---

## 七大弱點 vs. 對應突出功能

| # | Google A2A 弱點（來源：arxiv 2505.12490） | 本系統對應功能 | 檔案 |
|---|---|---|---|
| 1 | **Overbroad token / 無生命週期控制**<br>OAuth2/API Key 全域有效，無 task 綁定，無自動過期 | **Ephemeral Scoped Capability Token**<br>綁定 WorkContract+task，有 expires_at，可即時撤銷，防 privilege escalation | `interop/capability-token-lifecycle.yaml`<br>`interop/schemas/capability-token.json` |
| 2 | **無 Consent 流程**<br>敏感操作（payment、PII、identity docs）無用戶確認機制 | **Consent Orchestration**<br>操作級機讀 consent manifest + 不可刪改稽核軌跡 + 協定層強制閘門 | `interop/consent-orchestration.yaml`<br>`interop/schemas/consent-manifest.json` |
| 3 | **Implicit Trust**<br>通過 auth 的 agent 享有全部宣告能力，無歷史考量 | **Agent Reputation & Trust Scoring**<br>動態 trust_score（0.0–1.0），四層 tier，衰減機制，防刷分 | `interop/agent-reputation.yaml`<br>`interop/schemas/agent-reputation.json` |
| 4 | **無語意漂移偵測**<br>task 狀態只有 Completed/Failed，hallucination 無法被攔截 | **Semantic Drift Detection**<br>keyword 覆蓋率 + 指標比對 + 禁止變更偵測；自動拒絕閾值 0.4 | `interop/semantic-drift.yaml`<br>`interop/schemas/semantic-drift-report.json` |
| 5 | **無回滾機制**<br>task 失敗後副作用殘留，無法協調多代理還原 | **Multi-Agent Rollback Coordination**<br>full/partial/compensating 三種策略 + 快照機制 + 回滾後驗證 | `interop/rollback-coordination.yaml`<br>`interop/schemas/rollback-plan.json` |
| 6 | **無資源 Budget 上限**<br>代理可無限消耗 LLM token/算力，失控帳單 | **Resource & Cost Governance**<br>task 強制帶 resource_budget；超限自動終止；overflow_action 可組合 | `interop/resource-governance.yaml`<br>`interop/schemas/resource-budget.json` |
| 7 | **純通訊協定，無執行治理**<br>不管「怎麼做」，只管「怎麼說話」 | **A2A Bridge + GaaP 執行治理**<br>相容 A2A transport/discovery；在 message 注入治理元數據 | `interop/a2a-bridge.yaml`<br>`interop/schemas/agent-card-extended.json` |

---

## 我們原本就有（進一步拉開差距）

| 功能 | 說明 | Google A2A 有？ |
|---|---|---|
| **WorkContract 綁定協商** | 雙方交換 capability+constraints → 產生帶 hash 的 WorkContract；後續所有動作引用，防 scope creep | ✗ |
| **Artifact Registry + Content Hash** | 工件登記、版本、hash、不可變性；agent 只能基於 artifact 工作，不靠「我記得你說過」 | ✗ |
| **Policy-as-Code 執行閘門** | message 帶 policy_context（contract hash）；接收方回 policy_check_result；fail 不 execute | ✗ |
| **No-rewrite 語意（change_mode）** | patch_only / refactor_limited / rewrite_allowed；rewrite 需附 evidence | ✗ |
| **Objective Verification DSL** | 驗收條件是機器可執行的（test_commands、metric_thresholds、regression_scenarios），不是作文 | ✗ |
| **Observability（OTel/SIEM）** | trace_id、span_id、decision_log、tool_call_audit；可匯出 OpenTelemetry/SIEM | 部分（僅 audit log）|
| **Provenance Chain（SBOM-like）** | artifact 來源、衍生關係、hash；供應鏈化的代理交付 | ✗ |
| **Pre-commit + CI 硬治理** | 違規 commit/PR 直接被擋；不是「建議」，是「拒絕權」 | ✗ |
| **Complexity Budget（budgets.yaml）** | 單次變更：新增檔案數、依賴數、public functions、diff 行數均有上限 | ✗ |
| **ADR 決策帳本（機讀）** | 每個重要決策有 YAML ADR，可機驗、可追溯 | ✗ |

---

## 架構對比圖

```
Google A2A                          本系統（GaaP）
──────────────────────────          ──────────────────────────────────────────
Agent Card (discovery)              Agent Card Extended (A2A-compatible + GaaP)
   └─ capabilities                     └─ capabilities (A2A)
                                        └─ gaap_governance (新增)
                                           ├─ reputation
                                           ├─ consent_requirements
                                           ├─ resource_limits
                                           └─ token_policy

JSON-RPC message                    JSON-RPC message + gaap_meta (注入)
   └─ params                           └─ params
      └─ capability_id                    └─ capability_id (A2A)
      └─ parameters                       └─ parameters (A2A)
                                          └─ gaap_meta (新增)
                                             ├─ work_contract_id
                                             ├─ capability_token_id
                                             ├─ policy_context
                                             ├─ trace_id / span_id
                                             ├─ consent_grant_ref
                                             └─ resource_budget_ref

Task states                         Coordination Protocol states
   Created → Working                   propose → review → approve
   → NeedsInput → Completed            → execute (policy gate)
   → Failed / Canceled                 → verify (semantic drift check)
                                        → close (rollback if needed)
```

---

## 執行流程對比

### Google A2A（5 步）
1. Agent Card 發布（discovery）
2. 協商任務（tasks/send）
3. 執行（Working 狀態）
4. 交付（Completed/Failed）
5. 結束

### 本系統 GaaP（13 步，每步可機驗）
1. Agent Card Extended 發布（A2A 相容 + GaaP 治理元數據）
2. 能力協商（exchange capability + constraints）
3. **產生 WorkContract（hash 綁定，防 scope creep）**
4. **發放 Ephemeral Capability Token（短命、限域）**
5. **Policy Check**（policy_context → policy_check_result）
6. **Consent Gate**（敏感操作需明確同意）
7. **建立 Snapshot**（供回滾使用）
8. 執行（change_mode 生效；resource_budget 監控）
9. **語意漂移偵測**（drift_score < 0.4 才過）
10. **Objective Verification**（機器執行 acceptance_criteria）
11. **交付帶 delivery_envelope**（artifact_hash、build_repro、test_report_hash）
12. **Artifact 登記**（content hash + provenance chain）
13. **Token 撤銷 + change_log 記錄 + CI 驗證**

---

## 相容性聲明

> **"A2A-compatible, enterprise-grade Governance-as-a-Protocol"**

- A2A 的 transport、discovery、message 格式完整保留
- 現有 A2A 端無需修改即可互通
- GaaP 治理層以非侵入式方式注入 `gaap_meta`
- 現有 A2A SDK（LangGraph、CrewAI、Google ADK）可直接橋接

---

## 參考來源

- Google A2A 弱點研究：[arxiv 2505.12490](https://arxiv.org/html/2505.12490v3)「Improving Google A2A Protocol」
- Google A2A 官方文件：[google.github.io/A2A](https://google.github.io/A2A/)
- Google A2A 技術文件：[google-a2a.wiki](https://google-a2a.wiki/technical-documentation/)
