# AI ↔ AI 互通層（Interop）

本目錄定義 **多代理對接** 的協議與工作交付物規格，讓 AI 之間能「對接工作」而非只在聊天室互噴。  
與下層 `ai-governance/`（同 repo 內不亂改）互補：**interop = 跨代理的共通語言**。

---

## 六個基礎面向 + 八項企業級升級（均為可機讀、可驗證）

### 基礎六面向

| # | 面向 | 檔案 | 說明 |
|---|------|------|------|
| 1 | **Agent Identity / Capability** | `schemas/agent-identity.json`、`agents/*.yaml` | 身份與能力宣告：能做/不能做、工具權限、I/O schema、SLA |
| 2 | **Task Ticket** | `schemas/task-ticket.json`、`tasks/*.yaml` | AI 工單語言：objective、acceptance_criteria、inputs、deliverables、handoff_protocol、work_contract_id、change_mode、acceptance_verification |
| 3 | **Shared Artifacts Registry** | `schemas/artifact-registry.json`、`artifacts-registry.yaml` | 工件登記與引用：artifact ID、version/lineage、location、schema、immutability |
| 4 | **Coordination Protocol** | `coordination-protocol.yaml` + schema | 狀態機 + Handshake；policy_gate、work_contract_binding、delivery_envelope 整合 |
| 5 | **Conflict & Ownership** | `conflict-ownership.yaml` + schema | 責任邊界：owner、arbiter、並行改動政策、merge policy |
| 6 | **Security / Trust** | `security-trust.yaml` + schema | 權限最小化、capability token、artifact 信任、provenance chain、工具沙箱 |

### 八項企業級升級

| # | 升級 | 檔案 | 說明 |
|---|------|------|------|
| 1 | **Deterministic Artifacts** | `schemas/delivery-envelope.json`、`deterministic-artifacts.yaml` | 每次交付必附 artifact_hash、build_repro、inputs_hash、test_report_hash；僅基於 artifact 工作（供應鏈化） |
| 2 | **Policy-as-Code** | `schemas/policy-context.json`、`policy-check-result.json`、`policy-as-code.yaml` | message 帶 policy_context(contract hash)；接收方回 policy_check_result；fail 不 execute |
| 3 | **No Rewrite 語意** | `schemas/change-mode.json`、`no-rewrite-semantics.yaml` | change_mode：patch_only/refactor_limited/rewrite_allowed；rewrite 需 evidence；touching stable 需 diff_budget+rollback |
| 4 | **Negotiation that binds** | `schemas/work-contract.json`、`negotiation-binds.yaml` | 先交換 capability+constraints → WorkContract(hash)；後續所有動作引用 work_contract_id，防 scope creep |
| 5 | **Trust & Isolation** | `schemas/provenance-chain.json`、`security-trust.yaml` 擴充 | capability token 發放；untrusted 走 sandbox pipeline；provenance chain（SBOM-like） |
| 6 | **Observability & Audit** | `schemas/observability.json`、`observability-audit.yaml` | trace_id、span_id、decision_log、tool_call_audit；匯出 OpenTelemetry/SIEM |
| 7 | **Objective Verification DSL** | `schemas/acceptance-verification.json`、`objective-verification-dsl.yaml` | 驗收語言：test_commands、metric_thresholds、regression_scenarios；可機械驗收 |
| 8 | **A2A Compatibility** | [COMPATIBILITY.md](COMPATIBILITY.md) | Transport/discovery 兼容 A2A；上層加 WorkContract+Artifact+Policy gates；"A2A-compatible, enterprise-grade execution governance" |

---

## 對接流程（簡要）

1. **Owner** 依 Task Ticket 產出工單，inputs 僅引用 Artifacts Registry；可選 **acceptance_verification** DSL。  
2. **協商綁定**：交換 capability+constraints → 產生 **WorkContract** (hash)；後續皆帶 work_contract_id。  
3. **Consumer** 回 accept/reject + 預估需求；Owner 補 inputs。**Policy**：message 帶 policy_context；Consumer 回 policy_check_result；fail 不能 execute。  
4. **執行**：change_mode 與 no-rewrite 語意生效；交付時必附 **delivery_envelope**（artifact_hash、build_repro、inputs_hash、test_report_hash）。  
5. **驗收**：依 objective verification DSL 機械驗收；**Observability**：trace_id、span_id、decision_log、tool_call_audit 可匯出 OTel/SIEM。  
6. **Trust**：capability token、provenance chain、untrusted 走 sandbox。

---

## 驗證

- 所有 YAML/JSON 可依 `schemas/*.json` 做 CI 驗證。  
- 執行：`python ../scripts/validate_interop.py`（或納入既有 `validate_schemas.py`）。
