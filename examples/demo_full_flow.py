"""
demo_full_flow.py — GaaP vs Google A2A 端到端對比 Demo

執行方式：
    python examples/demo_full_flow.py

展示七個場景：
  S1. 正常 GaaP 流程（全部通過）
  S2. Token 過期（Ephemeral Token 保護）
  S3. 缺少 Consent（敏感資料操作被攔截）
  S4. 信任分數不足（低分代理被限制）
  S5. 語意漂移過高（deliverable 偏離 objective）
  S6. 資源預算超支（LLM 費用超限）
  S7. A2A（無 GaaP）vs GaaP 並排對比
"""
from __future__ import annotations

import time
from gaap_runtime import (
    EphemeralTokenRegistry,
    ConsentGate,
    TrustScoreEngine,
    SemanticDriftDetector,
    RollbackCoordinator,
    ResourceGuard,
    PolicyGate,
    GaaPGateway,
    make_contract_hash,
)

# ANSI 顏色（支援大多數終端）
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


def banner(title: str) -> None:
    print(f"\n{BOLD}{CYAN}{'─'*60}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─'*60}{RESET}")


def show(result: object, indent: int = 2) -> None:
    from gaap_runtime import GaaPResult
    if isinstance(result, GaaPResult):
        color = GREEN if result.passed else RED
        mark  = "[OK]" if result.passed else "[FAIL]"
        pad   = " " * indent
        print(f"{pad}{color}{mark} {result}{RESET}")
        if result.details:
            for k, v in result.details.items():
                print(f"{pad}  {YELLOW}  {k}: {v}{RESET}")
    else:
        print(f"{'  ' * indent}{result}")


def section(label: str) -> None:
    print(f"\n  {BOLD}[ {label} ]{RESET}")


# ─────────────────────────────────────────────────────────────────────────────
# 共用初始化
# ─────────────────────────────────────────────────────────────────────────────

CONTRACT_TEXT = "project:GaaP-demo version:1.0 invariants:[INV-API-001,INV-MOD-002]"
CONTRACT_HASH = make_contract_hash(CONTRACT_TEXT)

def build_gateway(token_ttl: int = 300) -> tuple[GaaPGateway, EphemeralTokenRegistry, ConsentGate, TrustScoreEngine, ResourceGuard, RollbackCoordinator]:
    registry    = EphemeralTokenRegistry()
    consent     = ConsentGate()
    trust       = TrustScoreEngine()
    drift       = SemanticDriftDetector()
    rollback    = RollbackCoordinator()
    resources   = ResourceGuard()
    policy      = PolicyGate(contract_hash=CONTRACT_HASH)
    gateway = GaaPGateway(registry, consent, trust, drift, rollback, resources, policy)
    return gateway, registry, consent, trust, resources, rollback


# ─────────────────────────────────────────────────────────────────────────────
# S1: 正常 GaaP 流程（全部通過）
# ─────────────────────────────────────────────────────────────────────────────

def scenario_1_happy_path() -> None:
    banner("S1: 正常 GaaP 流程 — 所有檢查通過")
    gw, registry, consent, trust, resources, rollback = build_gateway()

    AGENT   = "code-agent-alpha"
    WC_ID   = "WC-2025-001"
    TASK_ID = "TASK-001"

    section("Step 1: 發放 Ephemeral Capability Token（TTL=300s）")
    token = registry.issue(AGENT, WC_ID, ["backend_impl", "read_file"], ttl_seconds=300, task_id=TASK_ID)
    print(f"  Token ID : {token.token_id}")
    print(f"  Scoped   : {token.scoped_capabilities}")
    print(f"  Expires  : {300}s 後")

    section("Step 2: 敏感操作取得 Consent")
    cr = consent.request_consent("read_sensitive_data", ["user_email", "api_key"], TASK_ID)
    consent.grant(cr.consent_id, granted_by="human@example.com")
    print(f"  Consent ID: {cr.consent_id}  狀態: {cr.status}")

    section("Step 3: 建立 Resource Budget（$2.00 / 300s）")
    budget = resources.create_budget(TASK_ID, token_cost_ceiling=2.00, compute_budget_seconds=300, tool_calls_max=50)
    resources.record_usage(budget.budget_id, token_cost=0.45, compute_seconds=12, tool_calls=3)

    section("Step 4: GaaP 授權閘門（Policy + Token + Trust + Consent + Resource）")
    passed, results = gw.authorize_execute(
        token_id=token.token_id,
        work_contract_id=WC_ID,
        requested_capability="backend_impl",
        agent_id=AGENT,
        operation_type="read_sensitive_data",
        consent_grant_ref=cr.consent_id,
        budget_id=budget.budget_id,
        policy_context={"contract_hash": CONTRACT_HASH},
    )
    for r in results:
        show(r)

    section("Step 5: 語意漂移偵測")
    ok, drift_result = gw.verify_delivery(
        objective="在 data_loader 模組新增單元測試，coverage >= 80%",
        objective_keywords=["data_loader", "單元測試", "coverage", "80%"],
        deliverable_summary="新增了 test_load_prices.py，tests 全部通過，coverage=85%，未修改 public API",
        metric_thresholds={"coverage_min_percent": 80},
        actual_metrics={"coverage_min_percent": 85},
    )
    show(drift_result)

    print(f"\n  {GREEN}{BOLD}→ S1 結果：{'PASS — 進入 execute 狀態' if passed and ok else 'FAIL'}{RESET}")


# ─────────────────────────────────────────────────────────────────────────────
# S2: Token 過期
# ─────────────────────────────────────────────────────────────────────────────

def scenario_2_expired_token() -> None:
    banner("S2: Token 過期 — Ephemeral Token 保護生效")
    gw, registry, consent, trust, resources, _ = build_gateway()

    AGENT = "stale-agent"
    WC_ID = "WC-2025-002"
    print(f"\n  情境：代理持有一枚「剛好一秒前就過期」的 Token")
    print(f"  Google A2A：OAuth2 Token 預設有效期 1 小時以上，過期不會立即被攔截")

    token = registry.issue(AGENT, WC_ID, ["backend_impl"], ttl_seconds=-1)  # 已過期
    budget = resources.create_budget("TASK-002")
    cr = consent.request_consent("read_file", ["filename"], "TASK-002")
    consent.grant(cr.consent_id)

    _, results = gw.authorize_execute(
        token_id=token.token_id,
        work_contract_id=WC_ID,
        requested_capability="backend_impl",
        agent_id=AGENT,
        operation_type="read_file",
        consent_grant_ref=cr.consent_id,
        budget_id=budget.budget_id,
        policy_context={"contract_hash": CONTRACT_HASH},
    )
    for r in results:
        show(r)

    print(f"\n  {RED}{BOLD}→ S2 結果：Token 過期，GaaP 攔截成功（A2A 無此保護）{RESET}")


# ─────────────────────────────────────────────────────────────────────────────
# S3: 缺少 Consent（敏感資料操作）
# ─────────────────────────────────────────────────────────────────────────────

def scenario_3_no_consent() -> None:
    banner("S3: 缺少 Consent — 敏感資料操作被攔截")
    gw, registry, consent, trust, resources, _ = build_gateway()

    AGENT = "rogue-agent"
    WC_ID = "WC-2025-003"
    print(f"\n  情境：代理直接嘗試讀取 payment credentials，未取得同意")
    print(f"  Google A2A：無 consent 機制，arxiv 2505.12490 明確指出此缺陷")

    token = registry.issue(AGENT, WC_ID, ["credential_access"], ttl_seconds=300)
    budget = resources.create_budget("TASK-003")

    _, results = gw.authorize_execute(
        token_id=token.token_id,
        work_contract_id=WC_ID,
        requested_capability="credential_access",
        agent_id=AGENT,
        operation_type="credential_access",   # 敏感操作
        consent_grant_ref=None,               # 故意缺少
        budget_id=budget.budget_id,
        policy_context={"contract_hash": CONTRACT_HASH},
    )
    for r in results:
        show(r)

    print(f"\n  {RED}{BOLD}→ S3 結果：ConsentGate 攔截（A2A 完全無此層保護）{RESET}")


# ─────────────────────────────────────────────────────────────────────────────
# S4: 信任分數不足
# ─────────────────────────────────────────────────────────────────────────────

def scenario_4_low_trust() -> None:
    banner("S4: 信任分數不足 — 低分代理被限制至 sandbox")
    gw, registry, consent, trust, resources, _ = build_gateway()

    AGENT = "unreliable-agent"
    WC_ID = "WC-2025-004"
    print(f"\n  情境：代理有 3 次 policy violation 與 2 次 consent 違規")
    print(f"  Google A2A：通過 auth 即信任，無歷史績效考量")

    # 模擬過去的惡劣記錄
    for _ in range(3):
        trust.record_event(AGENT, "policy_violation")
    for _ in range(2):
        trust.record_event(AGENT, "consent_violation")

    score = trust.get_or_create(AGENT)
    print(f"  累積 trust_score: {score.trust_score:.2f}（tier: {score.tier()}）")

    token = registry.issue(AGENT, WC_ID, ["backend_impl"], ttl_seconds=300)
    budget = resources.create_budget("TASK-004")
    cr = consent.request_consent("read_file", ["filename"], "TASK-004")
    consent.grant(cr.consent_id)

    _, results = gw.authorize_execute(
        token_id=token.token_id,
        work_contract_id=WC_ID,
        requested_capability="backend_impl",
        agent_id=AGENT,
        operation_type="read_file",
        consent_grant_ref=cr.consent_id,
        budget_id=budget.budget_id,
        policy_context={"contract_hash": CONTRACT_HASH},
        required_trust_tier="standard",
    )
    for r in results:
        show(r)

    print(f"\n  {RED}{BOLD}→ S4 結果：TrustScore 攔截（A2A 對此毫無防範）{RESET}")


# ─────────────────────────────────────────────────────────────────────────────
# S5: 語意漂移過高
# ─────────────────────────────────────────────────────────────────────────────

def scenario_5_semantic_drift() -> None:
    banner("S5: 語意漂移 — Deliverable 偏離 Objective 被自動拒絕")
    print(f"\n  情境：要求「新增單元測試，coverage ≥ 80%」，但代理交付了完全不相關的 API 文件")
    print(f"  Google A2A：task 狀態僅有 Completed/Failed，無語意層驗證")

    drift = SemanticDriftDetector()
    result = drift.detect(
        objective="在 data_loader 模組新增單元測試，coverage >= 80%",
        objective_keywords=["data_loader", "單元測試", "coverage", "80%"],
        deliverable_summary="更新了 API 文件，新增了 REST endpoint 說明，修改了 README",
        metric_thresholds={"coverage_min_percent": 80},
        actual_metrics={"coverage_min_percent": 0},    # 完全沒跑測試
        forbidden_changes_detected=True,                # 還動了不應該動的東西
    )
    show(result)

    print(f"\n  {RED}{BOLD}→ S5 結果：drift_score={result.details.get('drift_score')}，自動拒絕（A2A 看不到這層）{RESET}")


# ─────────────────────────────────────────────────────────────────────────────
# S6: 資源預算超支
# ─────────────────────────────────────────────────────────────────────────────

def scenario_6_resource_overflow() -> None:
    banner("S6: 資源超支 — LLM 費用超過預算上限")
    print(f"\n  情境：task budget $0.50，但代理已用掉 $3.27（一直在呼叫 LLM）")
    print(f"  Google A2A：無任何 budget 機制，代理可無限消耗")

    resources = ResourceGuard()
    budget = resources.create_budget(
        "TASK-006",
        token_cost_ceiling=0.50,
        compute_budget_seconds=60,
        tool_calls_max=10,
        overflow_action="terminate",
    )
    resources.record_usage(budget.budget_id, token_cost=3.27, compute_seconds=45, tool_calls=8)
    result = resources.check(budget.budget_id)
    show(result)

    print(f"\n  {RED}{BOLD}→ S6 結果：ResourceGuard 攔截，overflow_action=terminate（A2A 無此機制）{RESET}")


# ─────────────────────────────────────────────────────────────────────────────
# S7: A2A vs GaaP 並排對比
# ─────────────────────────────────────────────────────────────────────────────

def scenario_7_side_by_side() -> None:
    banner("S7: Google A2A vs GaaP — 相同任務，不同防護等級")

    a2a_request = {
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "params": {
            "capability_id": "backend_impl",
            "parameters": {"task_id": "TASK-007", "objective": "讀取 payment credentials"},
        },
        "id": "req-a2a-001",
    }

    gaap_request = {
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "params": {
            "capability_id": "backend_impl",
            "parameters": {"task_id": "TASK-007", "objective": "讀取 payment credentials"},
            "gaap_meta": {
                "work_contract_id": "WC-2025-007",
                "capability_token_id": "tok-abc123",
                "policy_context": {"contract_hash": CONTRACT_HASH},
                "trace_id": "trace-xyz-789",
                "span_id": "span-001",
                "consent_grant_ref": "consent-456",        # 需要通過 ConsentGate
                "resource_budget_ref": "budget-task007",   # 需要通過 ResourceGuard
            },
        },
        "id": "req-gaap-001",
    }

    import json
    section("Google A2A 請求（無治理元數據）")
    print("  " + json.dumps(a2a_request, ensure_ascii=False, indent=4).replace("\n", "\n  "))
    print(f"\n  {YELLOW}A2A 保護：OAuth2 認證 → 直接執行（無 token 生命週期、無 consent 檢查、無 drift 偵測）{RESET}")

    section("GaaP 請求（七層治理元數據）")
    print("  " + json.dumps(gaap_request, ensure_ascii=False, indent=4).replace("\n", "\n  "))
    print(f"\n  {GREEN}GaaP 保護：Policy ✓ → Token ✓ → Trust ✓ → Consent ✓ → Resource ✓ → Drift ✓ → 執行{RESET}")

    print(f"\n  {BOLD}關鍵差異：gaap_meta 是非侵入式的——現有 A2A 接收端自動忽略此欄位{RESET}")
    print(f"  {BOLD}GaaP-aware 接收端則逐層驗證後才允許 execute{RESET}")


# ─────────────────────────────────────────────────────────────────────────────
# 主程式
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"\n{BOLD}{'═'*60}{RESET}")
    print(f"{BOLD}  GaaP（Governance-as-a-Protocol）執行期 Demo{RESET}")
    print(f"{BOLD}  對應 Google A2A 七大弱點的七個真實場景{RESET}")
    print(f"{BOLD}{'═'*60}{RESET}")

    scenario_1_happy_path()
    scenario_2_expired_token()
    scenario_3_no_consent()
    scenario_4_low_trust()
    scenario_5_semantic_drift()
    scenario_6_resource_overflow()
    scenario_7_side_by_side()

    print(f"\n{BOLD}{CYAN}{'═'*60}{RESET}")
    print(f"{BOLD}{CYAN}  Demo 完成 — 以上所有攔截均由 gaap_runtime.py 執行{RESET}")
    print(f"{BOLD}{CYAN}  無需額外依賴，Python 3.9+ 標準函式庫即可執行{RESET}")
    print(f"{BOLD}{CYAN}{'═'*60}{RESET}\n")


if __name__ == "__main__":
    main()
