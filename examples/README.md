# GaaP Examples — 可執行 Demo

本目錄提供 Governance-as-a-Protocol（GaaP）的**真實可跑**範例，
展示七大突出模組如何在執行期攔截 Google A2A 的七大安全弱點。

---

## 執行需求

- Python **3.9+**
- **無額外依賴**（gaap_runtime.py 與 demo_full_flow.py 完全使用標準函式庫）
- agent_server.py 同樣使用標準 `http.server`，不需要 Flask / FastAPI

---

## 快速開始

### Option A — 一鍵 Demo（最推薦）

```bash
cd examples
python demo_full_flow.py
```

七個場景，全部在終端輸出，約 2 秒執行完畢。
預錄輸出見 [`sample_output.txt`](sample_output.txt)。

### Option B — Agent Server + Client（模擬真實 A2A 互通）

```bash
# 終端 1：啟動 GaaP Agent Server
python examples/agent_server.py

# 終端 2：發送 A2A vs GaaP 請求
python examples/agent_client.py
```

---

## 檔案說明

| 檔案 | 說明 | 依賴 |
|---|---|---|
| **`gaap_runtime.py`** | GaaP 執行期核心函式庫（七大模組） | stdlib only |
| **`demo_full_flow.py`** | 端到端 Demo，七個場景 | gaap_runtime |
| **`agent_server.py`** | A2A-compatible + GaaP 代理伺服器 | gaap_runtime |
| **`agent_client.py`** | 發送 A2A vs GaaP 請求並對比結果 | stdlib only |
| **`sample_output.txt`** | demo_full_flow.py 的預錄輸出 | — |

---

## 七個 Demo 場景

| 場景 | 測試模組 | 攔截結果 |
|---|---|---|
| S1. 正常流程 | 全部 | 全部通過，進入 execute |
| S2. Token 過期 | EphemeralToken | FAIL — Token 過期被攔截 |
| S3. 缺少 Consent | ConsentGate | FAIL — 敏感操作缺少同意 |
| S4. 信任分數不足 | TrustScore | FAIL — sandbox_only tier，低於要求 |
| S5. 語意漂移過高 | SemanticDrift | FAIL — drift_score=1.0，自動拒絕 |
| S6. 資源預算超支 | ResourceGuard | FAIL — token_cost $3.27 > budget $0.50 |
| S7. A2A vs GaaP | 並排對比 | 展示 gaap_meta 非侵入式注入 |

---

## gaap_runtime.py API 摘要

```python
from gaap_runtime import (
    EphemeralTokenRegistry,   # Token 發放 / 撤銷 / 驗證
    EphemeralTokenValidator,  # 驗證 token_id + work_contract_id + capability
    ConsentGate,              # 同意閘門（request / grant / deny / check）
    TrustScoreEngine,         # 動態信任評分（record_event / check_capability）
    SemanticDriftDetector,    # 語意漂移偵測（detect → GaaPResult）
    RollbackCoordinator,      # 多代理回滾（register_snapshot / initiate / execute）
    ResourceGuard,            # 資源預算（create_budget / record_usage / check）
    PolicyGate,               # Policy-as-Code 閘門
    GaaPGateway,              # 統一入口（authorize_execute / verify_delivery）
)

# 完整執行期授權（5 層並發）
gateway.authorize_execute(
    token_id="tok-xxx",
    work_contract_id="WC-001",
    requested_capability="backend_impl",
    agent_id="my-agent",
    operation_type="read_file",
    consent_grant_ref="consent-abc",
    budget_id="budget-001",
    policy_context={"contract_hash": "sha256:..."},
)
# → (all_passed: bool, results: list[GaaPResult])

# 交付前語意驗收
gateway.verify_delivery(
    objective="新增單元測試，coverage >= 80%",
    objective_keywords=["單元測試", "coverage", "80%"],
    deliverable_summary="test_xxx.py 通過，coverage=85%",
    metric_thresholds={"coverage_min_percent": 80},
    actual_metrics={"coverage_min_percent": 85},
)
# → (passed: bool, drift_result: GaaPResult)
```

---

## Agent Server API

伺服器啟動後提供：

| Endpoint | Method | 說明 |
|---|---|---|
| `/.well-known/agent.json` | GET | Extended Agent Card（A2A-compatible + GaaP） |
| `/tasks/send` | POST | JSON-RPC 2.0 任務接收（A2A + GaaP 授權） |
| `/health` | GET | 健康檢查 + demo 憑證摘要 |
| `/demo-credentials` | GET | 取得 demo 用 token_id / consent_id |

無 `gaap_meta` → A2A-only 模式（有警告）  
有 `gaap_meta` → 七層 GaaP 授權閘門全部執行

---

## 與 Google A2A 的差異（用數字說話）

| 指標 | Google A2A | GaaP |
|---|---|---|
| Token 生命週期 | 無（全域有效） | TTL + 自動過期 + 即時撤銷 |
| Consent 檢查 | 無 | 操作級，7 種敏感類型 |
| 信任評分層級 | 無（通過即信任） | 4 tier（full/standard/restricted/sandbox） |
| Hallucination 攔截 | 無 | drift_score threshold 0.4 |
| 回滾協調 | 無 | full/partial/compensating |
| 資源預算 | 無 | token cost + compute + tool_calls |
| 執行保護層數 | 1（auth）| 7（Policy+Token+Trust+Consent+Resource+Drift+Rollback）|
