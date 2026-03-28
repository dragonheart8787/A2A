"""
agent_server.py — 最小可跑的 A2A-compatible + GaaP 代理伺服器

使用 Python 標準函式庫（http.server），無額外依賴。

功能：
  - GET  /.well-known/agent.json → Extended Agent Card（A2A 相容 + GaaP 治理元數據）
  - POST /tasks/send             → JSON-RPC 2.0 任務接收（A2A 標準 + gaap_meta 解析）
  - GET  /health                 → 健康檢查

GaaP 治理邏輯（由 gaap_runtime.py 提供）：
  1. Ephemeral Token 驗證
  2. Consent Gate 檢查
  3. Trust Score 檢查
  4. Resource Budget 監控
  5. Policy Gate 驗證

執行方式：
    python examples/agent_server.py [port=8080]

測試方式：
    python examples/agent_client.py          # 發送範例請求
    curl http://localhost:8080/health
    curl http://localhost:8080/.well-known/agent.json
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

# 從同目錄匯入 GaaP 執行期
import os
sys.path.insert(0, os.path.dirname(__file__))
from gaap_runtime import (
    ConsentGate,
    EphemeralTokenRegistry,
    GaaPGateway,
    PolicyGate,
    ResourceGuard,
    RollbackCoordinator,
    SemanticDriftDetector,
    TrustScoreEngine,
    make_contract_hash,
)

# ─────────────────────────────────────────────────────────────────────────────
# GaaP Gateway 初始化（伺服器層級共享）
# ─────────────────────────────────────────────────────────────────────────────

CONTRACT_HASH = make_contract_hash("project:GaaP-demo version:1.0")
TOKEN_REGISTRY = EphemeralTokenRegistry()
CONSENT_GATE   = ConsentGate()
TRUST_ENGINE   = TrustScoreEngine()
DRIFT_DETECTOR = SemanticDriftDetector()
ROLLBACK_COORD = RollbackCoordinator()
RESOURCE_GUARD = ResourceGuard()
POLICY_GATE    = PolicyGate(contract_hash=CONTRACT_HASH)

GATEWAY = GaaPGateway(
    TOKEN_REGISTRY, CONSENT_GATE, TRUST_ENGINE,
    DRIFT_DETECTOR, ROLLBACK_COORD, RESOURCE_GUARD, POLICY_GATE,
)

# 預先發放一枚 Demo Token（供 agent_client.py 使用）
DEMO_TOKEN = TOKEN_REGISTRY.issue(
    agent_id="demo-client-agent",
    work_contract_id="WC-DEMO-001",
    scoped_capabilities=["code_review", "backend_impl", "read_file"],
    ttl_seconds=3600,
    task_id=None,
)
# 預先建立一個已授予的 Consent（供 demo 使用）
DEMO_CONSENT = CONSENT_GATE.request_consent("read_file", ["source_code"], "DEMO-TASK")
CONSENT_GATE.grant(DEMO_CONSENT.consent_id, granted_by="demo-human")

# ─────────────────────────────────────────────────────────────────────────────
# Agent Card（A2A-compatible + GaaP 治理元數據）
# ─────────────────────────────────────────────────────────────────────────────

AGENT_CARD = {
    "spec": "agent-card-extended",
    "version": "1.0.0",
    "a2a_compatible": True,
    "agent_id": "gaap-demo-agent",
    "name": "GaaP Demo Agent",
    "description": "A2A-compatible agent with Governance-as-a-Protocol enforcement",
    "contact": "gaap@example.com",
    "endpoints": {
        "tasks": "http://localhost:8080/tasks/send",
        "stream": None,
        "agent_card": "http://localhost:8080/.well-known/agent.json",
    },
    "auth": {
        "type": "capability_token",
        "in": "gaap_meta",
        "name": "capability_token_id",
    },
    "capabilities": [
        {
            "id": "code_review",
            "name": "Code Review",
            "description": "Review code for quality and compliance",
            "requires_consent": False,
            "min_trust_score": 0.4,
        },
        {
            "id": "backend_impl",
            "name": "Backend Implementation",
            "description": "Implement backend features with GaaP governance",
            "requires_consent": False,
            "min_trust_score": 0.6,
        },
        {
            "id": "credential_access",
            "name": "Credential Access",
            "description": "Access sensitive credentials (requires consent)",
            "requires_consent": True,
            "min_trust_score": 0.8,
        },
    ],
    "gaap_governance": {
        "reputation": {
            "trust_score": 0.9,
            "tier": "full",
            "last_updated": "2026-03-28T00:00:00Z",
        },
        "consent_requirements": [
            {"operation_type": "credential_access", "consent_required_from": "human"},
            {"operation_type": "payment_operation", "consent_required_from": "human"},
        ],
        "resource_limits": {
            "token_cost_ceiling_per_task": 2.0,
            "compute_budget_seconds_per_task": 300,
            "tool_calls_max_per_task": 50,
        },
        "token_policy": {
            "requires_ephemeral_token": True,
            "token_max_lifetime_seconds": 3600,
            "supports_token_rotation": True,
        },
        "no_rewrite_semantics": "patch_only",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# HTTP 請求處理器
# ─────────────────────────────────────────────────────────────────────────────

class GaaPRequestHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"  [Server] {fmt % args}")

    def _send_json(self, status: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path in ("/.well-known/agent-card.json", "/.well-known/agent.json"):
            # 同時支援 A2A SDK >= v0.3.x 的新路徑與舊路徑（backward compatibility）
            self._send_json(200, AGENT_CARD)

        elif self.path == "/health":
            self._send_json(200, {
                "status": "ok",
                "agent_id": "gaap-demo-agent",
                "demo_token_id": DEMO_TOKEN.token_id,
                "demo_consent_id": DEMO_CONSENT.consent_id,
                "contract_hash": CONTRACT_HASH,
            })

        elif self.path == "/demo-credentials":
            """回傳 demo 用的 token_id 與 consent_id，供 client 直接使用"""
            self._send_json(200, {
                "token_id": DEMO_TOKEN.token_id,
                "consent_id": DEMO_CONSENT.consent_id,
                "work_contract_id": "WC-DEMO-001",
                "contract_hash": CONTRACT_HASH,
            })

        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        if self.path != "/tasks/send":
            self._send_json(404, {"error": "Not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            req = json.loads(raw)
        except json.JSONDecodeError as e:
            self._send_json(400, {"error": f"Invalid JSON: {e}"})
            return

        req_id = req.get("id", "unknown")
        params  = req.get("params", {})
        cap_id  = params.get("capability_id", "")
        gaap    = params.get("gaap_meta", {})

        print(f"\n  [GaaP] 收到任務請求 id={req_id!r}  capability={cap_id!r}")

        # ── A2A-only 請求（無 gaap_meta）──────────────────────────────────
        if not gaap:
            print("  [GaaP] ⚠ 無 gaap_meta — 以純 A2A 模式處理（無治理保護）")
            self._send_json(200, {
                "jsonrpc": "2.0",
                "result": {
                    "status": "accepted",
                    "task_id": str(uuid.uuid4()),
                    "governance": "none (A2A-only mode)",
                    "warning": "No GaaP governance applied. Consider adding gaap_meta for enterprise-grade protection.",
                },
                "id": req_id,
            })
            return

        # ── GaaP 授權閘門 ─────────────────────────────────────────────────
        task_id = params.get("parameters", {}).get("task_id", str(uuid.uuid4()))
        budget = RESOURCE_GUARD.create_budget(
            task_id,
            token_cost_ceiling=2.0,
            compute_budget_seconds=300,
            tool_calls_max=50,
        )

        passed, results = GATEWAY.authorize_execute(
            token_id=gaap.get("capability_token_id", ""),
            work_contract_id=gaap.get("work_contract_id", ""),
            requested_capability=cap_id,
            agent_id=params.get("parameters", {}).get("agent_id", "unknown"),
            operation_type=params.get("parameters", {}).get("operation_type", "read_file"),
            consent_grant_ref=gaap.get("consent_grant_ref"),
            budget_id=budget.budget_id,
            policy_context=gaap.get("policy_context", {}),
        )

        governance_report = {
            "passed": passed,
            "checks": [
                {"module": r.module, "passed": r.passed, "message": r.message}
                for r in results
            ],
        }

        if not passed:
            failed = [r for r in results if not r.passed]
            print(f"  [GaaP] ✗ 授權失敗：{[r.module for r in failed]}")
            self._send_json(200, {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32001,
                    "message": "GaaP authorization failed",
                    "data": governance_report,
                },
                "id": req_id,
            })
            return

        print(f"  [GaaP] ✓ 授權通過，進入 execute 狀態")

        # 模擬任務執行
        result_payload = {
            "status": "completed",
            "task_id": task_id,
            "capability_id": cap_id,
            "output": f"任務 {task_id} 已由 gaap-demo-agent 完成（受 GaaP 全程治理）",
            "artifact_hash": "sha256:" + "demo" * 8,
            "gaap_result": governance_report,
        }

        print(f"  [GaaP] ✓ 任務 {task_id!r} 完成")
        self._send_json(200, {"jsonrpc": "2.0", "result": result_payload, "id": req_id})


# ─────────────────────────────────────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = HTTPServer(("", port), GaaPRequestHandler)
    print(f"\n{'═'*55}")
    print(f"  GaaP Demo Agent Server")
    print(f"{'═'*55}")
    print(f"  Agent Card : http://localhost:{port}/.well-known/agent-card.json  (A2A SDK >= v0.3.x)")
    print(f"             : http://localhost:{port}/.well-known/agent.json        (backward compat)")
    print(f"  Tasks API  : http://localhost:{port}/tasks/send")
    print(f"  Health     : http://localhost:{port}/health")
    print(f"  Credentials: http://localhost:{port}/demo-credentials")
    print(f"{'═'*55}")
    print(f"  Demo Token : {DEMO_TOKEN.token_id}")
    print(f"  Demo Consent: {DEMO_CONSENT.consent_id}")
    print(f"  Contract Hash: {CONTRACT_HASH}")
    print(f"{'─'*55}")
    print(f"  執行 agent_client.py 以發送測試請求")
    print(f"  Ctrl+C 停止伺服器")
    print(f"{'═'*55}\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  伺服器已停止。")


if __name__ == "__main__":
    main()
