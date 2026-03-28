# AI ↔ AI 互通層（Interop）— Governance-as-a-Protocol

> **定位**：本目錄定義多代理對接的協議、規格與工作交付物。  
> 與 Google A2A 的根本差異：**A2A 是通訊協定；本系統是執行治理協定（GaaP）。**  
> 詳見根目錄 [GOVERNANCE_VS_A2A.md](../../GOVERNANCE_VS_A2A.md)。

---

## 完整規格覽表

### 原有六大基礎面向

| # | 面向 | 規格檔 | Schema | 說明 |
|---|------|--------|--------|------|
| 1 | **Agent Identity / Capability** | `agents/*.yaml` | `schemas/agent-identity.json` | 身份與能力宣告；工具權限、I/O schema、SLA |
| 2 | **Task Ticket** | `tasks/*.yaml` | `schemas/task-ticket.json` | AI 工單語言：objective、acceptance_criteria、inputs、deliverables |
| 3 | **Shared Artifacts Registry** | `artifacts-registry.yaml` | `schemas/artifact-registry.json` | 工件登記：artifact ID、version/lineage、hash、immutability |
| 4 | **Coordination Protocol** | `coordination-protocol.yaml` | `schemas/coordination-protocol.json` | 狀態機 + Handshake；policy_gate、WorkContract、delivery_envelope |
| 5 | **Conflict & Ownership** | `conflict-ownership.yaml` | `schemas/conflict-ownership.json` | 責任邊界：owner、arbiter、並行改動政策 |
| 6 | **Security / Trust** | `security-trust.yaml` | `schemas/security-trust.json` | 權限最小化、artifact 信任、provenance chain、tool 沙箱 |

### 原有八項企業級升級

| # | 升級 | 規格檔 | Schema | 說明 |
|---|------|--------|--------|------|
| 1 | **Deterministic Artifacts** | `deterministic-artifacts.yaml` | `schemas/delivery-envelope.json` | 交付必附 artifact_hash、build_repro、inputs_hash、test_report_hash |
| 2 | **Policy-as-Code** | `policy-as-code.yaml` | `schemas/policy-context.json`<br>`schemas/policy-check-result.json` | message 帶 policy_context；接收方回 policy_check_result；fail 不 execute |
| 3 | **No Rewrite 語意** | `no-rewrite-semantics.yaml` | `schemas/change-mode.json` | change_mode：patch_only/refactor_limited/rewrite_allowed |
| 4 | **Negotiation that Binds** | `negotiation-binds.yaml` | `schemas/work-contract.json` | 先協商 → WorkContract(hash)；後續引用，防 scope creep |
| 5 | **Trust & Isolation** | `security-trust.yaml`（擴充） | `schemas/provenance-chain.json` | capability token、provenance chain（SBOM-like） |
| 6 | **Observability & Audit** | `observability-audit.yaml` | `schemas/observability.json` | trace_id、span_id、decision_log、tool_call_audit；OTel/SIEM 匯出 |
| 7 | **Objective Verification DSL** | `objective-verification-dsl.yaml` | `schemas/acceptance-verification.json` | test_commands、metric_thresholds、regression_scenarios |
| 8 | **A2A Compatibility（舊版）** | `COMPATIBILITY.md` | — | Transport/discovery 兼容 A2A（已升級為 A2A Bridge，見下） |

---

### 新增七大突出模組（GaaP vs Google A2A）

| # | 模組 | 規格檔 | Schema | 對應 A2A 弱點 |
|---|------|--------|--------|--------------|
| 1 | **Ephemeral Scoped Capability Token** | `capability-token-lifecycle.yaml` | `schemas/capability-token.json` | Overbroad token；無生命週期控制；Privilege escalation |
| 2 | **Consent Orchestration** | `consent-orchestration.yaml` | `schemas/consent-manifest.json` | 無 consent flow；sensitive data 無用戶確認 |
| 3 | **Agent Reputation & Trust Scoring** | `agent-reputation.yaml` | `schemas/agent-reputation.json` | Implicit trust；任意代理均被信任 |
| 4 | **Semantic Drift Detection** | `semantic-drift.yaml` | `schemas/semantic-drift-report.json` | 無語意漂移攔截；hallucination 悄悄進入產線 |
| 5 | **Multi-Agent Rollback Coordination** | `rollback-coordination.yaml` | `schemas/rollback-plan.json` | 無回滾機制；失敗副作用殘留無法清除 |
| 6 | **Resource & Cost Governance** | `resource-governance.yaml` | `schemas/resource-budget.json` | 無 budget 上限；代理可無限消耗 token/算力 |
| 7 | **A2A Bridge Adapter** | `a2a-bridge.yaml` | `schemas/agent-card-extended.json` | 純通訊協定；無執行治理；A2A 相容橋接 |

---

## 完整對接流程（13 步，每步可機驗）

```
1. Agent Card Extended 發布（/.well-known/agent.json，A2A 相容 + GaaP 治理元數據）
2. 能力協商（exchange capability + constraints）
3. 產生 WorkContract（hash 綁定）              ← negotiation-binds.yaml
4. 發放 Ephemeral Capability Token             ← capability-token-lifecycle.yaml [新]
5. Policy Check                                ← policy-as-code.yaml
6. Consent Gate（敏感操作必過）                ← consent-orchestration.yaml [新]
7. 建立 Snapshot（供回滾用）                   ← rollback-coordination.yaml [新]
8. 執行（change_mode + resource_budget 監控）  ← no-rewrite-semantics.yaml + resource-governance.yaml [新]
9. 語意漂移偵測（drift_score < 0.4 才過）      ← semantic-drift.yaml [新]
10. Objective Verification（機器驗收）          ← objective-verification-dsl.yaml
11. 交付 delivery_envelope                     ← deterministic-artifacts.yaml
12. Artifact 登記（hash + provenance chain）    ← artifacts-registry.yaml + security-trust.yaml
13. Token 撤銷 + change_log + CI 驗證          ← capability-token-lifecycle.yaml + enforce.py
```

---

## 新增 MVP 校驗（enforce.py）

在原有五條 MVP 基礎上，新增：

| # | 校驗 | 說明 |
|---|------|------|
| MVP 6 | **Resource Budget 校驗** | task 帶 resource_budget 時，actual_usage 不得超出 limits |
| MVP 7 | **Consent Gate 校驗** | 含敏感操作的 task，delivery_envelope 必須有 consent_grant_ref |

---

## 驗證

所有 YAML/JSON 可依 `schemas/*.json` 做 CI 驗證：

```bash
# 驗證全部（含新增七大模組）
python ai-governance/scripts/validate_interop.py

# 或從根目錄
python validate_schemas.py
```

---

## 相容性聲明

> **"A2A-compatible, enterprise-grade Governance-as-a-Protocol"**

- A2A transport / discovery / message 格式完整保留
- 現有 A2A 端無需修改即可互通
- GaaP 治理層以非侵入式方式注入 `gaap_meta`（在 JSON-RPC params 中）
- 詳見 [a2a-bridge.yaml](a2a-bridge.yaml) 與 [COMPATIBILITY.md](COMPATIBILITY.md)
