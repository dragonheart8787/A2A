"""
agent_client.py — 展示 A2A 請求 vs GaaP 請求的差異

使用 Python 標準函式庫，無額外依賴。

執行方式（需先啟動 agent_server.py）：
    # 終端 1
    python examples/agent_server.py

    # 終端 2
    python examples/agent_client.py [server_url=http://localhost:8080]

發送三種請求並對比結果：
  C1. 純 A2A 請求（無 gaap_meta）—— 被警告但可執行
  C2. GaaP 請求（正確憑證）—— 全部通過
  C3. GaaP 請求（偽造 token）—— 被攔截
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Any

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

BASE_URL = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8080"


def banner(title: str) -> None:
    print(f"\n{BOLD}{CYAN}{'─'*60}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─'*60}{RESET}")


def http_get(path: str) -> dict:
    url = BASE_URL + path
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        print(f"{RED}  連線失敗：{e}{RESET}")
        print(f"{YELLOW}  請先執行：python examples/agent_server.py{RESET}")
        sys.exit(1)


def http_post(path: str, body: dict) -> tuple[int, dict]:
    url = BASE_URL + path
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())
    except urllib.error.URLError as e:
        print(f"{RED}  連線失敗：{e}{RESET}")
        sys.exit(1)


def pretty(data: dict, indent: int = 2) -> None:
    pad = " " * indent
    for line in json.dumps(data, ensure_ascii=False, indent=2).splitlines():
        print(pad + line)


def main() -> None:
    print(f"\n{BOLD}{'═'*60}{RESET}")
    print(f"{BOLD}  GaaP Agent Client — A2A vs GaaP 請求對比{RESET}")
    print(f"{BOLD}  Server: {BASE_URL}{RESET}")
    print(f"{BOLD}{'═'*60}{RESET}")

    # ── 取得 Agent Card ───────────────────────────────────────────────────
    banner("Step 0: 取得 Extended Agent Card（A2A Discovery）")
    card = http_get("/.well-known/agent.json")
    print(f"  name        : {card.get('name')}")
    print(f"  a2a_compatible: {card.get('a2a_compatible')}")
    print(f"  capabilities  : {[c['id'] for c in card.get('capabilities', [])]}")
    gov = card.get("gaap_governance", {})
    rep = gov.get("reputation", {})
    print(f"  trust_score   : {rep.get('trust_score')}（{rep.get('tier')} tier）")
    limits = gov.get("resource_limits", {})
    print(f"  token_cost_ceiling: ${limits.get('token_cost_ceiling_per_task')}/task")
    print(f"  {GREEN}→ 這是 A2A-compatible + GaaP 治理元數據的 Extended Agent Card{RESET}")

    # ── 取得 demo 憑證 ────────────────────────────────────────────────────
    creds = http_get("/demo-credentials")
    token_id      = creds["token_id"]
    consent_id    = creds["consent_id"]
    wc_id         = creds["work_contract_id"]
    contract_hash = creds["contract_hash"]

    # ── C1: 純 A2A 請求（無 gaap_meta） ──────────────────────────────────
    banner("C1: 純 A2A 請求（無 gaap_meta）")
    print(f"  情境：這是一個標準 Google A2A JSON-RPC 請求，沒有任何 GaaP 治理欄位")

    a2a_req = {
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "params": {
            "capability_id": "backend_impl",
            "parameters": {"task_id": "TASK-A2A-001"},
        },
        "id": "req-a2a-001",
    }
    print(f"\n  {BOLD}請求：{RESET}")
    pretty(a2a_req)

    status, resp = http_post("/tasks/send", a2a_req)
    print(f"\n  {BOLD}回應：{RESET}")
    pretty(resp)
    result = resp.get("result", {})
    warn   = result.get("warning", "")
    if warn:
        print(f"\n  {YELLOW}⚠ 伺服器警告：{warn}{RESET}")
    print(f"\n  {YELLOW}→ A2A 模式：接受請求但無任何治理保護{RESET}")

    # ── C2: GaaP 請求（正確憑證，全部通過） ──────────────────────────────
    banner("C2: GaaP 請求（正確憑證）")
    print(f"  情境：相同任務，加上 gaap_meta（Token + Consent + Policy + Resource Budget）")

    gaap_req = {
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "params": {
            "capability_id": "backend_impl",
            "parameters": {
                "task_id": "TASK-GAAP-002",
                "agent_id": "demo-client-agent",
                "operation_type": "read_file",
            },
            "gaap_meta": {
                "work_contract_id": wc_id,
                "capability_token_id": token_id,
                "policy_context": {"contract_hash": contract_hash},
                "trace_id": "trace-abc-001",
                "span_id": "span-001",
                "consent_grant_ref": consent_id,
                "resource_budget_ref": "budget-auto",
            },
        },
        "id": "req-gaap-002",
    }
    print(f"\n  {BOLD}請求（含 gaap_meta）：{RESET}")
    pretty(gaap_req)

    status, resp = http_post("/tasks/send", gaap_req)
    print(f"\n  {BOLD}回應：{RESET}")
    pretty(resp)
    if resp.get("result", {}).get("status") == "completed":
        checks = resp.get("result", {}).get("gaap_result", {}).get("checks", [])
        print(f"\n  {GREEN}✓ 所有 GaaP 檢查通過：{RESET}")
        for c in checks:
            mark = f"{GREEN}✓{RESET}" if c["passed"] else f"{RED}✗{RESET}"
            print(f"    {mark} {c['module']}: {c['message']}")
    print(f"\n  {GREEN}→ GaaP 模式：七層治理全部通過，任務執行{RESET}")

    # ── C3: GaaP 請求（偽造 token，被攔截） ──────────────────────────────
    banner("C3: GaaP 請求（偽造 token）")
    print(f"  情境：攻擊者偽造 token_id，嘗試繞過授權")

    fake_req = {
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "params": {
            "capability_id": "credential_access",
            "parameters": {
                "task_id": "TASK-HACK-003",
                "agent_id": "hacker-agent",
                "operation_type": "credential_access",
            },
            "gaap_meta": {
                "work_contract_id": wc_id,
                "capability_token_id": "tok-FAKE000000",    # 偽造 token
                "policy_context": {"contract_hash": contract_hash},
                "trace_id": "trace-hack-999",
                "span_id": "span-hack",
                "consent_grant_ref": None,                   # 缺少 consent
                "resource_budget_ref": "budget-auto",
            },
        },
        "id": "req-hack-003",
    }
    print(f"\n  {BOLD}請求（偽造憑證）：{RESET}")
    pretty(fake_req)

    status, resp = http_post("/tasks/send", fake_req)
    print(f"\n  {BOLD}回應：{RESET}")
    pretty(resp)
    if resp.get("error"):
        err_data = resp["error"].get("data", {})
        failed = [c for c in err_data.get("checks", []) if not c["passed"]]
        print(f"\n  {RED}✗ GaaP 攔截失敗項目：{RESET}")
        for c in failed:
            print(f"    {RED}✗{RESET} {c['module']}: {c['message']}")
    print(f"\n  {RED}→ GaaP 攔截：偽造 Token 立即被拒（A2A 無此防護）{RESET}")

    print(f"\n{BOLD}{'═'*60}{RESET}")
    print(f"{BOLD}  對比總結{RESET}")
    print(f"{'─'*60}")
    print(f"  C1 A2A-only : 無 token 驗證，無 consent 檢查，直接接受請求")
    print(f"  C2 GaaP     : 七層治理全部通過，安全執行")
    print(f"  C3 攻擊者   : 偽造 token 立即被 EphemeralTokenValidator 攔截")
    print(f"{BOLD}{'═'*60}{RESET}\n")


if __name__ == "__main__":
    main()
