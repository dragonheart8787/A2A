# A2A Compatibility Layer

**定位**：不是取代 A2A，而是「吞掉它」——協議的 transport / discovery **兼容 A2A**（可轉接），在上層加上 **WorkContract + Artifact + Policy gates**，對外宣稱：

> **"A2A-compatible, but enterprise-grade execution governance."**

市場上「打標準」很難；**兼容標準再升級**才是贏法。A2A 本來就是為互操作而生。

---

## 兼容範圍

| 層級 | 作法 |
|------|------|
| **Transport / Discovery** | 與 A2A 相容的通道與發現機制（可轉接、可橋接） |
| **Message 格式** | 在 A2A message 之上擴充必備欄位，不破壞既有 payload |

## 本協議在上層新增的治理層

| 能力 | 說明 |
|------|------|
| **WorkContract** | 協商後產生綁定 hash；後續所有動作引用，防 scope creep |
| **Artifact 第一公民** | 交付必附 artifact_hash、build_repro、inputs_hash、test_report_hash；僅基於 artifact 工作 |
| **Policy gates** | message 帶 policy_context (contract hash)；接收方回 policy_check_result；fail 不 execute |
| **No Rewrite 語意** | change_mode、evidence、diff_budget、rollback 寫進協議 |
| **Trust & Provenance** | capability token、artifact 信任、provenance chain（SBOM-like） |
| **Observability** | trace_id、span_id、decision_log、tool_call_audit；可匯出 OTel / SIEM |
| **Objective verification** | 驗收 DSL（test_commands、metric_thresholds、regression_scenarios） |

---

## 實作建議

- **A2A 端**：維持既有 transport、discovery、message 格式。
- **本協議**：在 message envelope 或 metadata 中注入 `policy_context`、`work_contract_id`、`trace_id`、`delivery_envelope` 等；接收端先跑 policy check、WorkContract 綁定檢查，再決定是否 execute。
- **對外**：標註 "A2A-compatible, enterprise-grade execution governance"。
