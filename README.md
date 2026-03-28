# Governance-as-a-Protocol（GaaP）

> **"A2A-compatible, enterprise-grade Governance-as-a-Protocol"**  
> 不只是 AI 通訊協定——讓每一條指令都帶有可機驗治理元數據的執行治理框架。

---

## 30 秒看懂差異

```
Google A2A                          本系統（GaaP）
──────────────────────────────      ─────────────────────────────────────
通訊協定（怎麼說話）                執行治理協定（怎麼安全地做事）
auth → 直接執行                     Policy→Token→Trust→Consent→Resource→Drift→執行
無 Token 生命週期                   Ephemeral Token（綁 task，有 TTL，可撤銷）
無 Consent 流程                     操作級同意閘門 + 不可刪改稽核軌跡
Implicit Trust                      動態 trust_score（0.0–1.0），四層 tier
task 狀態只有 Completed/Failed      語意漂移偵測（drift_score>0.4 自動拒絕）
無回滾機制                          多代理協調回滾（full/partial/compensating）
無 Budget 上限                      per-task resource_budget（超限自動終止）
```

---

## 可直接執行的 Demo

> **無需任何額外依賴，Python 3.9+ 標準函式庫即可。**

```bash
# clone 後立即執行
git clone https://github.com/dragonheart8787/A2A.git
cd A2A
python examples/demo_full_flow.py
```

### Demo 輸出片段（七個場景）

```
S2: Token 過期 — Ephemeral Token 保護生效
  情境：代理持有一枚「剛好一秒前就過期」的 Token
  Google A2A：OAuth2 Token 預設有效期 1 小時以上，過期不會立即被攔截

  [OK]   PolicyGate    : Policy 驗證通過（contract_hash 符合）
  [FAIL] EphemeralToken: Token 已過期 1 秒
           expired_at: 2026-03-28T06:29:18+00:00
  [OK]   TrustScore    : 信任分數 0.70，通過
  [OK]   ConsentGate   : 操作 'read_file' 不需要同意
  [OK]   ResourceGuard : 資源用量正常

  → S2 結果：GaaP 攔截成功（A2A 無此保護）

S3: 缺少 Consent — 敏感資料操作被攔截
  [FAIL] ConsentGate: 敏感操作 'credential_access' 缺少 consent_grant_ref
           required_from: human

S6: 資源超支 — LLM 費用超過預算上限
  情境：task budget $0.50，但代理已用掉 $3.27
  [FAIL] ResourceGuard: token_cost: 3.270 > ceiling 0.5
           overflow_action: terminate
```

完整輸出見 [`examples/sample_output.txt`](examples/sample_output.txt)。

### Agent Server + Client（模擬真實 A2A 互通）

```bash
# 終端 1
python examples/agent_server.py

# 終端 2（另開）
python examples/agent_client.py
```

Client 發出三種請求並對比結果：
- **C1 純 A2A**：無 gaap_meta，有警告但允許執行
- **C2 GaaP 正常**：七層全部通過，任務執行
- **C3 偽造 Token**：立即被 EphemeralTokenValidator 攔截

---

## 執行期架構（gaap_runtime.py）

```python
from gaap_runtime import GaaPGateway

# 執行前授權（5 層並發）
passed, results = gateway.authorize_execute(
    token_id="tok-xxx",
    work_contract_id="WC-001",
    requested_capability="backend_impl",
    agent_id="my-agent",
    operation_type="credential_access",
    consent_grant_ref="consent-abc",   # 無則 ConsentGate FAIL
    budget_id="budget-001",
    policy_context={"contract_hash": "sha256:..."},
)

# 交付前語意驗收
passed, drift = gateway.verify_delivery(
    objective="新增單元測試，coverage >= 80%",
    objective_keywords=["單元測試", "coverage", "80%"],
    deliverable_summary="test_xxx.py 通過，coverage=85%",
    metric_thresholds={"coverage_min_percent": 80},
    actual_metrics={"coverage_min_percent": 85},
)
```

---

## 七大突出模組（對應 A2A 七大弱點）

| # | 模組 | 對應 A2A 弱點 | 落地證據 |
|---|---|---|---|
| 1 | Ephemeral Scoped Capability Token | Overbroad token；無過期機制 | `gaap_runtime.EphemeralTokenValidator` |
| 2 | Consent Orchestration | 無 consent flow（arxiv 2505.12490）| `gaap_runtime.ConsentGate` |
| 3 | Agent Reputation & Trust Scoring | Implicit trust；任意代理均信任 | `gaap_runtime.TrustScoreEngine` |
| 4 | Semantic Drift Detection | 無 hallucination 協定層攔截 | `gaap_runtime.SemanticDriftDetector` |
| 5 | Multi-Agent Rollback Coordination | 無回滾；副作用殘留 | `gaap_runtime.RollbackCoordinator` |
| 6 | Resource & Cost Governance | 無 budget；代理可無限消耗 | `gaap_runtime.ResourceGuard` |
| 7 | A2A Bridge Adapter | 純通訊協定；無執行治理 | `examples/agent_server.py` |

---

## 七條 MVP 校驗（CI 強制）

`enforce.py` 在每次 commit/PR 時自動執行全部七條：

| # | 校驗 | 失敗訊息範例 |
|---|---|---|
| 1 | change_log 必填 | `ENFORCE: 有程式變更但未新增 change_log 記錄` |
| 2 | touched_files 一致 | `ENFORCE: touched_files 未包含實際變更檔案: ['src/foo.py']` |
| 3 | stable 模組 diff 限制 | `ENFORCE: 單檔變更 87 行超過上限 50` |
| 4 | 依賴 Allowlist | `ENFORCE: 新增依賴 'requests' 未在 allowlist 核准` |
| 5 | breaking 須 rollback_plan | `ENFORCE: breaking change 未填 rollback_plan` |
| **6** | **Resource Budget** | `ENFORCE [MVP6]: token_cost 3.27 > ceiling 0.50` |
| **7** | **Consent Gate** | `ENFORCE [MVP7]: 敏感操作缺少 consent_grant_ref` |

```bash
# 手動執行
python ai-governance/scripts/enforce.py
```

---

## 原有企業級基礎（持續保留）

| 功能 | 說明 | Google A2A 有？ |
|---|---|---|
| WorkContract 綁定協商 | 防 scope creep；hash 綁定 | ✗ |
| Artifact Registry + Content Hash | 工件供應鏈化 | ✗ |
| Policy-as-Code 執行閘門 | 違規則拒絕 execute | ✗ |
| No-rewrite 語意（change_mode） | patch_only / refactor / rewrite | ✗ |
| Objective Verification DSL | 機器執行的驗收條件 | ✗ |
| Observability（OTel/SIEM） | trace/span/decision_log/tool_audit | 部分 |
| Provenance Chain（SBOM-like）| artifact 溯源鏈 | ✗ |
| Pre-commit + CI 硬治理 | 違規直接擋；七條 MVP | ✗ |

---

## 快速開始

```bash
# 1. 安裝驗證依賴（CI / pre-commit 用）
pip install -r ai-governance/scripts/requirements.txt

# 2. 跑 GaaP Demo（無額外依賴）
python examples/demo_full_flow.py

# 3. 驗證所有 Schema
python validate_schemas.py

# 4. 執行七條 MVP 校驗
python ai-governance/scripts/enforce.py

# 5. 安裝 pre-commit（本地 commit 前自動執行）
pip install pre-commit && pre-commit install
```

---

## 目錄結構

```
.
├── examples/                         ← 可執行 Demo（無額外依賴）
│   ├── gaap_runtime.py               ← 七大模組執行期函式庫 [核心]
│   ├── demo_full_flow.py             ← 端到端 Demo（7 個場景）
│   ├── agent_server.py               ← A2A-compatible GaaP 代理伺服器
│   ├── agent_client.py               ← A2A vs GaaP 請求對比
│   ├── sample_output.txt             ← 預錄 Demo 輸出
│   └── README.md                     ← Examples 說明
├── GOVERNANCE_VS_A2A.md              ← GaaP vs A2A 完整對比表
├── validate_schemas.py               ← 根目錄快速驗證入口
├── .pre-commit-config.yaml
├── .github/workflows/                ← CI：Schema + 七條 MVP
└── ai-governance/
    ├── contract.md / architecture.md / modules.yaml / workflow.yaml / budgets.yaml
    ├── change_log.jsonl              ← 不可刪改的變更帳本
    ├── decisions/                    ← ADR 機讀化決策帳本
    ├── schemas/                      ← 治理層 JSON Schema
    ├── scripts/
    │   ├── enforce.py                ← 七條 MVP 校驗
    │   ├── validate_schemas.py
    │   └── validate_interop.py       ← 含七大 GaaP 模組驗證
    └── interop/
        ├── a2a-bridge.yaml           ← A2A Bridge Adapter
        ├── capability-token-lifecycle.yaml
        ├── consent-orchestration.yaml
        ├── agent-reputation.yaml
        ├── semantic-drift.yaml
        ├── rollback-coordination.yaml
        ├── resource-governance.yaml
        └── schemas/                  ← 14 個 JSON Schema
```

---

## 參考來源

- Google A2A 弱點研究：[arxiv 2505.12490](https://arxiv.org/html/2505.12490v3)
- Google A2A 官方：[google.github.io/A2A](https://google.github.io/A2A/)
- 詳細對比：[GOVERNANCE_VS_A2A.md](GOVERNANCE_VS_A2A.md)
