# Governance-as-a-Protocol（GaaP）

> **"A2A-compatible, enterprise-grade Governance-as-a-Protocol"**  
> 不只是 AI 通訊協定，而是讓每一條指令都帶有可機驗治理元數據的執行治理框架。

---

## 為什麼需要 GaaP？

Google A2A 定義了 AI 代理之間「怎麼說話」，但沒有回答「怎麼安全地做事」。  
根據學術研究（[arxiv 2505.12490](https://arxiv.org/html/2505.12490v3)），A2A 存在七大企業級安全弱點：

| A2A 弱點 | 說明 |
|---|---|
| Overbroad Token | OAuth2/API Key 全域有效，無 task 綁定，無自動過期 |
| 無 Consent 流程 | 敏感資料操作（payment、PII）無用戶確認機制 |
| Implicit Trust | 通過驗證的 agent 直接獲得全部能力，無歷史績效考量 |
| 無語意漂移偵測 | Hallucination 無法在協定層被攔截 |
| 無回滾機制 | 任務失敗後副作用殘留，無法多代理協調還原 |
| 無 Budget 上限 | 代理可無限消耗 LLM token / 算力 |
| 純通訊協定 | 不管「怎麼做」，只管「怎麼說話」 |

**GaaP 針對每一項提出可機讀、可驗證、可繼承的解法。**

---

## 七大突出模組

### 1. Ephemeral Scoped Capability Token（短命限域令牌）
- Token 綁定 `work_contract_id` + `task_id`，有 `expires_at`，可即時撤銷
- 防 privilege escalation；不發放永久 / 全域 token
- 📄 [`interop/capability-token-lifecycle.yaml`](ai-governance/interop/capability-token-lifecycle.yaml)

### 2. Consent Orchestration（明確同意閘門）
- 敏感操作（payment、PII、credential access）前必須取得機讀同意
- 不可刪改的 consent audit trail，可匯出至 SIEM
- 📄 [`interop/consent-orchestration.yaml`](ai-governance/interop/consent-orchestration.yaml)

### 3. Agent Reputation & Trust Scoring（動態信任評分）
- 每個 agent 有 `trust_score`（0.0–1.0），依歷史績效動態調整
- 四層 tier（full / standard / restricted / sandbox_only）決定能力授予
- 衰減機制 + 防刷分設計
- 📄 [`interop/agent-reputation.yaml`](ai-governance/interop/agent-reputation.yaml)

### 4. Semantic Drift Detection（語意漂移偵測）
- 協定層比對 deliverable 與 task objective 的語意對齊度
- `drift_score > 0.4` 自動拒絕，防 hallucination 進入產線
- 📄 [`interop/semantic-drift.yaml`](ai-governance/interop/semantic-drift.yaml)

### 5. Multi-Agent Rollback Coordination（多代理回滾）
- 失敗時統一觸發，full / partial / compensating 三種策略
- 各 agent 依 `snapshot_ref` 還原；回滾後自動驗證
- 📄 [`interop/rollback-coordination.yaml`](ai-governance/interop/rollback-coordination.yaml)

### 6. Resource & Cost Governance（資源成本治理）
- task 強制帶 `resource_budget`（token_cost_ceiling、compute_budget_s）
- 超限 `overflow_action` 自動終止，防失控帳單
- 📄 [`interop/resource-governance.yaml`](ai-governance/interop/resource-governance.yaml)

### 7. A2A Bridge Adapter（相容橋接層）
- 完整保留 A2A transport / discovery / JSON-RPC 格式
- 在 `params.gaap_meta` 非侵入式注入治理元數據
- 現有 A2A 端無需修改即可互通
- 📄 [`interop/a2a-bridge.yaml`](ai-governance/interop/a2a-bridge.yaml)

---

## 原有企業級基礎（已有，持續保留）

| 功能 | 說明 |
|---|---|
| **WorkContract 綁定協商** | 防 scope creep；後續所有動作引用同一份 hash |
| **Artifact Registry + Content Hash** | 工件供應鏈化；agent 只能基於 artifact 工作 |
| **Policy-as-Code 執行閘門** | 違規 policy 則拒絕進入 execute 狀態 |
| **No-rewrite 語意（change_mode）** | patch_only / refactor_limited / rewrite_allowed |
| **Objective Verification DSL** | 驗收條件是機器可執行的，不是作文 |
| **Observability（OTel/SIEM）** | trace_id / span_id / decision_log / tool_call_audit |
| **Provenance Chain（SBOM-like）** | artifact 溯源鏈，供應鏈安全 |
| **Pre-commit + CI 硬治理** | 違規 commit/PR 直接被擋；七條 MVP 校驗 |

---

## 架構總覽

```
┌─────────────────────────────────────────────────────────┐
│                 GaaP 治理層（本系統）                     │
│                                                          │
│  1. Ephemeral Token    2. Consent Orchestration          │
│  3. Agent Reputation   4. Semantic Drift Detection       │
│  5. Rollback Coord.    6. Resource Governance            │
│  7. A2A Bridge ◄────────────────────────────────┐        │
│                                                  │        │
│  原有層：WorkContract / Artifact / Policy         │        │
│          No-rewrite / Observability / Provenance │        │
│          Pre-commit / CI                         │        │
├──────────────────────────────────────────────────┘        │
│                  A2A 通訊層（保留）                        │
│   Agent Card | tasks/send | SSE | JSON-RPC 2.0           │
└─────────────────────────────────────────────────────────┘
```

---

## 執行流程對比

| | Google A2A（5步） | 本系統 GaaP（13步） |
|---|---|---|
| 1 | Agent Card 發布 | Agent Card Extended 發布（A2A 相容 + GaaP 元數據） |
| 2 | 協商任務 | 能力協商 |
| 3 | — | **產生 WorkContract（hash 綁定）** |
| 4 | — | **發放 Ephemeral Capability Token** |
| 5 | — | **Policy Check** |
| 6 | — | **Consent Gate（敏感操作必過）** |
| 7 | — | **建立 Snapshot（供回滾用）** |
| 8 | 執行 | 執行（change_mode + resource_budget 監控） |
| 9 | — | **語意漂移偵測（drift_score < 0.4）** |
| 10 | — | **Objective Verification（機器驗收）** |
| 11 | 交付 | 交付帶 delivery_envelope（artifact_hash + build_repro） |
| 12 | — | **Artifact 登記（hash + provenance chain）** |
| 13 | 結束 | **Token 撤銷 + change_log 記錄 + CI 驗證** |

---

## 快速開始

### 1. 安裝依賴

```bash
pip install -r ai-governance/scripts/requirements.txt
```

### 2. 驗證所有 Schema（含七大 GaaP 模組）

```bash
python validate_schemas.py
```

### 3. 五條 MVP 校驗（含 MVP 6/7）

```bash
python ai-governance/scripts/enforce.py
```

### 4. 安裝 Pre-commit（本地自動攔截）

```bash
pip install pre-commit
pre-commit install
# 之後每次 git commit 自動執行
```

### 5. CI 自動化

Push 或 PR 時，GitHub Actions 自動執行：
- Schema 驗證
- 七條 MVP Enforcement
- 失敗時自動在 PR 留言缺失項

---

## 目錄結構

```
.
├── GOVERNANCE_VS_A2A.md          ← GaaP vs A2A 完整對比表
├── validate_schemas.py           ← 根目錄快速驗證入口
├── .pre-commit-config.yaml       ← 本地 commit 攔截
├── .github/workflows/            ← CI 自動化
└── ai-governance/
    ├── README.md                 ← 治理框架總說明
    ├── contract.md               ← 系統契約（不可侵犯原則）
    ├── architecture.md           ← 架構與 API 正典
    ├── modules.yaml              ← 模組邊界與穩定度
    ├── workflow.yaml             ← 狀態機（Idea→Released）
    ├── budgets.yaml              ← 複雜度預算
    ├── change_log.jsonl          ← 不可刪改的變更帳本
    ├── decisions/                ← ADR 決策帳本
    ├── schemas/                  ← 治理層 JSON Schema
    ├── scripts/
    │   ├── enforce.py            ← 七條 MVP 校驗（主腳本）
    │   ├── validate_schemas.py   ← Schema 驗證
    │   └── validate_interop.py  ← Interop 驗證（含七大 GaaP 模組）
    └── interop/
        ├── README.md             ← Interop 完整說明
        ├── COMPATIBILITY.md      ← A2A 相容橋接細節
        ├── a2a-bridge.yaml               ← A2A Bridge Adapter [新]
        ├── capability-token-lifecycle.yaml ← Ephemeral Token [新]
        ├── consent-orchestration.yaml    ← Consent Gate [新]
        ├── agent-reputation.yaml         ← Trust Scoring [新]
        ├── semantic-drift.yaml           ← Drift Detection [新]
        ├── rollback-coordination.yaml    ← Rollback Coord. [新]
        ├── resource-governance.yaml      ← Resource Budget [新]
        ├── coordination-protocol.yaml
        ├── negotiation-binds.yaml
        ├── policy-as-code.yaml
        ├── no-rewrite-semantics.yaml
        ├── observability-audit.yaml
        ├── objective-verification-dsl.yaml
        ├── deterministic-artifacts.yaml
        ├── security-trust.yaml
        ├── conflict-ownership.yaml
        ├── artifacts-registry.yaml
        ├── agents/                       ← Agent 身份宣告
        ├── tasks/                        ← Task Ticket 範例
        └── schemas/                      ← Interop JSON Schema（含七大 GaaP）
```

---

## 七條 MVP 校驗（CI 強制）

| # | 校驗 | 說明 |
|---|---|---|
| 1 | change_log 必填 | 有程式變更必須新增 change_log.jsonl 一筆 |
| 2 | touched_files 一致 | 與 git diff 實際變更檔案必須一致 |
| 3 | stable 模組限制 | 單檔 diff 不得超過 `stable_module_max_diff_lines`（預設 50 行） |
| 4 | 依賴 Allowlist | 新增依賴必須在 `modules.yaml dependency_allowlist` 中核准 |
| 5 | breaking 須 rollback | `breaking: true` 必須附 `rollback_plan` |
| **6** | **Resource Budget** | **actual_usage 不得超出 resource_budget.limits** |
| **7** | **Consent Gate** | **含敏感操作的 task 交付必須附 consent_grant_ref** |

---

## 詳細對比

見 [`GOVERNANCE_VS_A2A.md`](GOVERNANCE_VS_A2A.md) — 包含完整的 A2A 弱點分析、架構對比、欄位映射與遷移路徑。

---

## 參考資料

- Google A2A 弱點研究：[arxiv 2505.12490](https://arxiv.org/html/2505.12490v3)
- Google A2A 官方：[google.github.io/A2A](https://google.github.io/A2A/)
- Google A2A 技術文件：[google-a2a.wiki](https://google-a2a.wiki/technical-documentation/)
