"""
gaap_cli.py — GaaP Runtime CLI 管理工具

用途：查看 / 管理 GaaP 執行期狀態（token、consent、reputation、audit、contract、artifact）
依賴：Python stdlib only

執行方式：
    python examples/gaap_cli.py --help
    python examples/gaap_cli.py status
    python examples/gaap_cli.py tokens
    python examples/gaap_cli.py consents
    python examples/gaap_cli.py reputation
    python examples/gaap_cli.py audit
    python examples/gaap_cli.py contracts
    python examples/gaap_cli.py artifacts
    python examples/gaap_cli.py token issue --agent my-agent --wc WC-001 --caps read_file,backend_impl
    python examples/gaap_cli.py token revoke --id tok-abc123
    python examples/gaap_cli.py consent request --op credential_access --task T-001
    python examples/gaap_cli.py consent grant --id consent-abc123
    python examples/gaap_cli.py run-demo
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gaap_runtime import (
    ArtifactRegistry,
    ConsentGate,
    EphemeralTokenRegistry,
    GaaPPersistence,
    ObservabilityTracer,
    TrustScoreEngine,
    WorkContractManager,
    build_gateway,
    make_contract_hash,
)

DATA_DIR     = os.environ.get("GAAP_DATA_DIR", ".gaap_data")
CONTRACT_KEY = os.environ.get("GAAP_CONTRACT", "project:GaaP version:2.1.0")

# ─────────────────────────────────────────────────────────────────────────────
# 顯示工具
# ─────────────────────────────────────────────────────────────────────────────

BOLD  = "\033[1m"
GREEN = "\033[92m"
RED   = "\033[91m"
CYAN  = "\033[96m"
YELLOW= "\033[93m"
RESET = "\033[0m"


def _fmt_ts(ts: float | None) -> str:
    if ts is None:
        return "—"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _fmt_bool(b: bool) -> str:
    return f"{GREEN}yes{RESET}" if b else f"{RED}no{RESET}"


def _table(headers: list[str], rows: list[list[str]]) -> None:
    if not rows:
        print("  (none)")
        return
    widths = [max(len(h), max((len(str(r[i])) for r in rows), default=0)) for i, h in enumerate(headers)]
    sep = "  ".join("-" * w for w in widths)
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(f"  {fmt.format(*headers)}")
    print(f"  {sep}")
    for row in rows:
        print(f"  {fmt.format(*[str(c) for c in row])}")


def _load_persistence() -> GaaPPersistence:
    return GaaPPersistence(DATA_DIR)


# ─────────────────────────────────────────────────────────────────────────────
# 子命令：status
# ─────────────────────────────────────────────────────────────────────────────

def cmd_status(args: argparse.Namespace) -> None:
    p = _load_persistence()
    print(f"\n{BOLD}GaaP Runtime Status{RESET}")
    print(f"  data_dir   : {DATA_DIR}")
    print(f"  contract   : {CONTRACT_KEY[:60]}")
    print(f"  hash       : {make_contract_hash(CONTRACT_KEY)}")
    print()
    stores = ["tokens", "consents", "reputation", "audit", "contracts", "artifacts"]
    for s in stores:
        records = p.load_all(s)
        path    = p.data_path(s)
        exists  = path.exists()
        size    = f"{path.stat().st_size:,} bytes" if exists else "—"
        print(f"  {s:<12}: {len(records):>5} records  |  {size}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# 子命令：tokens
# ─────────────────────────────────────────────────────────────────────────────

def cmd_tokens(args: argparse.Namespace) -> None:
    p  = _load_persistence()
    reg = EphemeralTokenRegistry(p)
    tokens = reg.all_tokens()

    if args.filter_agent:
        tokens = [t for t in tokens if t.agent_id == args.filter_agent]

    print(f"\n{BOLD}Capability Tokens ({len(tokens)}){RESET}")
    rows = []
    for t in sorted(tokens, key=lambda x: x.issued_at, reverse=True):
        expired = t.is_expired()
        status  = "revoked" if t.revoked else ("expired" if expired else "active")
        color   = RED if t.revoked or expired else GREEN
        rows.append([
            t.token_id[:20],
            t.agent_id[:20],
            t.work_contract_id[:15],
            f"{color}{status}{RESET}",
            _fmt_ts(t.expires_at),
            f"{t.ttl_seconds():.0f}s" if not expired and not t.revoked else "—",
        ])
    _table(["token_id", "agent_id", "work_contract_id", "status", "expires_at", "ttl"], rows)
    print()


# ─────────────────────────────────────────────────────────────────────────────
# 子命令：consents
# ─────────────────────────────────────────────────────────────────────────────

def cmd_consents(args: argparse.Namespace) -> None:
    p  = _load_persistence()
    cg = ConsentGate(p)

    print(f"\n{BOLD}Consent Records ({len(cg.all_consents())}){RESET}")
    rows = []
    for cr in sorted(cg.all_consents(), key=lambda x: x.consent_id):
        color = {"granted": GREEN, "denied": RED, "pending": YELLOW, "expired": RED}.get(cr.status, RESET)
        rows.append([
            cr.consent_id[:20],
            cr.operation_type[:20],
            f"{color}{cr.status}{RESET}",
            cr.granted_by or "—",
            cr.task_id[:15] or "—",
        ])
    _table(["consent_id", "operation_type", "status", "granted_by", "task_id"], rows)
    print()


# ─────────────────────────────────────────────────────────────────────────────
# 子命令：reputation
# ─────────────────────────────────────────────────────────────────────────────

def cmd_reputation(args: argparse.Namespace) -> None:
    p   = _load_persistence()
    eng = TrustScoreEngine(p)

    snapshot = p.snapshot_latest("reputation", "agent_id")
    print(f"\n{BOLD}Agent Reputation ({len(snapshot)}){RESET}")
    rows = []
    for agent_id, rec in sorted(snapshot.items()):
        score = rec.get("trust_score", 0.7)
        tier_map = {
            lambda s: s >= 0.8: "full",
            lambda s: s >= 0.6: "standard",
            lambda s: s >= 0.4: "restricted",
        }
        if score >= 0.8:      tier = "full"
        elif score >= 0.6:    tier = "standard"
        elif score >= 0.4:    tier = "restricted"
        else:                 tier = "sandbox_only"
        color = GREEN if score >= 0.6 else (YELLOW if score >= 0.4 else RED)
        rows.append([
            agent_id[:25],
            f"{color}{score:.3f}{RESET}",
            tier,
            str(rec.get("tasks_completed", 0)),
            str(rec.get("policy_violations", 0)),
            str(rec.get("consent_violations", 0)),
        ])
    _table(["agent_id", "score", "tier", "tasks_ok", "violations", "consent_violations"], rows)
    print()


# ─────────────────────────────────────────────────────────────────────────────
# 子命令：audit
# ─────────────────────────────────────────────────────────────────────────────

def cmd_audit(args: argparse.Namespace) -> None:
    p       = _load_persistence()
    records = p.load_all("audit")

    if args.type:
        records = [r for r in records if r.get("_type") == args.type]
    if args.module:
        records = [r for r in records if r.get("module") == args.module]
    if args.limit:
        records = records[-args.limit:]

    print(f"\n{BOLD}Audit Log ({len(records)} entries){RESET}")
    for r in records:
        t    = r.get("_type", "?")
        ts   = r.get("timestamp", r.get("started_at", "?"))[:19]
        mod  = r.get("module", r.get("operation", r.get("tool", "?")))
        desc = r.get("reason", r.get("decision", r.get("tool", "")))[:60]
        ok   = r.get("result", r.get("status") == "ok")
        color = GREEN if ok else RED
        print(f"  {ts}  [{t:10}]  {color}{mod:<20}{RESET}  {desc}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# 子命令：contracts
# ─────────────────────────────────────────────────────────────────────────────

def cmd_contracts(args: argparse.Namespace) -> None:
    p   = _load_persistence()
    mgr = WorkContractManager(p)

    print(f"\n{BOLD}Work Contracts ({len(mgr.all_contracts())}){RESET}")
    rows = []
    for wc in mgr.all_contracts():
        color = GREEN if wc.status == "active" else (RED if wc.status == "violated" else YELLOW)
        rows.append([
            wc.work_contract_id[:20],
            f"{color}{wc.status}{RESET}",
            wc.contract_hash[:20],
            wc.scope_ref[:20],
            wc.created_at[:19],
        ])
    _table(["work_contract_id", "status", "hash", "scope_ref", "created_at"], rows)
    print()


# ─────────────────────────────────────────────────────────────────────────────
# 子命令：artifacts
# ─────────────────────────────────────────────────────────────────────────────

def cmd_artifacts(args: argparse.Namespace) -> None:
    p  = _load_persistence()
    ar = ArtifactRegistry(p)

    print(f"\n{BOLD}Artifact Registry ({len(ar.all_artifacts())}){RESET}")
    rows = []
    for a in ar.all_artifacts():
        color = GREEN if a.trust == "trusted" else (YELLOW if a.trust == "verified" else RED)
        rows.append([
            a.artifact_id[:20],
            a.version,
            f"{color}{a.trust}{RESET}",
            a.content_hash[:20],
            a.schema_type[:12],
            a.location[:25],
        ])
    _table(["artifact_id", "version", "trust", "content_hash", "schema_type", "location"], rows)
    print()


# ─────────────────────────────────────────────────────────────────────────────
# 子命令：token issue / revoke
# ─────────────────────────────────────────────────────────────────────────────

def cmd_token_issue(args: argparse.Namespace) -> None:
    p   = _load_persistence()
    reg = EphemeralTokenRegistry(p)
    caps = [c.strip() for c in args.caps.split(",")]
    tok = reg.issue(args.agent, args.wc, caps, ttl_seconds=args.ttl)
    print(f"\n{GREEN}Token issued:{RESET}")
    print(f"  token_id : {tok.token_id}")
    print(f"  agent_id : {tok.agent_id}")
    print(f"  wc_id    : {tok.work_contract_id}")
    print(f"  caps     : {tok.scoped_capabilities}")
    print(f"  ttl      : {args.ttl}s")
    print(f"  expires  : {_fmt_ts(tok.expires_at)}")
    print()


def cmd_token_revoke(args: argparse.Namespace) -> None:
    p   = _load_persistence()
    reg = EphemeralTokenRegistry(p)
    reg.revoke(args.id, reason=args.reason or "manual revoke via CLI")
    print(f"\n{GREEN}Token revoked:{RESET} {args.id}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# 子命令：consent request / grant / deny
# ─────────────────────────────────────────────────────────────────────────────

def cmd_consent_request(args: argparse.Namespace) -> None:
    p  = _load_persistence()
    cg = ConsentGate(p)
    fields = [f.strip() for f in args.fields.split(",")] if args.fields else ["(not specified)"]
    cr = cg.request_consent(args.op, fields, args.task or "")
    print(f"\n{YELLOW}Consent requested:{RESET}")
    print(f"  consent_id : {cr.consent_id}")
    print(f"  operation  : {cr.operation_type}")
    print(f"  status     : {cr.status}")
    print(f"  grant via  : python examples/gaap_cli.py consent grant --id {cr.consent_id}")
    print()


def cmd_consent_grant(args: argparse.Namespace) -> None:
    p  = _load_persistence()
    cg = ConsentGate(p)
    ok = cg.grant(args.id, granted_by=args.by or "human")
    if ok:
        print(f"\n{GREEN}Consent granted:{RESET} {args.id}")
    else:
        print(f"\n{RED}Failed to grant consent {args.id!r} (not found or expired){RESET}")
    print()


def cmd_consent_deny(args: argparse.Namespace) -> None:
    p  = _load_persistence()
    cg = ConsentGate(p)
    ok = cg.deny(args.id, reason=args.reason or "denied via CLI")
    if ok:
        print(f"\n{RED}Consent denied:{RESET} {args.id}")
    else:
        print(f"\n{RED}Failed to deny consent {args.id!r}{RESET}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# 子命令：run-demo（快速驗證 runtime 正常）
# ─────────────────────────────────────────────────────────────────────────────

def cmd_run_demo(args: argparse.Namespace) -> None:
    print(f"\n{BOLD}GaaP CLI Runtime Smoke Test{RESET}")
    print(f"  data_dir: {DATA_DIR}")
    print()

    gw, registry, consent_gate, trust, resources, rollback = build_gateway(
        contract_content=CONTRACT_KEY,
        data_dir=DATA_DIR,
        persist=True,
    )

    AGENT   = "cli-demo-agent"
    TASK_ID = f"CLI-TASK-{int(time.time())}"

    # 1. WorkContract
    wc = gw.contracts.create({}, {}, TASK_ID, [AGENT, "orchestrator"])
    print(f"  [1] WorkContract : {wc.work_contract_id} (hash={wc.contract_hash})")

    # 2. Token
    tok = registry.issue(AGENT, wc.work_contract_id, ["backend_impl"], ttl_seconds=300, task_id=TASK_ID)
    print(f"  [2] Token issued : {tok.token_id} (ttl=300s)")

    # 3. Consent
    cr = consent_gate.request_consent("read_file", ["source_code"], TASK_ID, ttl_seconds=3600)
    consent_gate.grant(cr.consent_id, granted_by="cli-admin")
    print(f"  [3] Consent      : {cr.consent_id} (status=granted)")

    # 4. Budget
    budget = resources.create_budget(TASK_ID, token_cost_ceiling=1.0, compute_budget_seconds=60)
    resources.record_usage(budget.budget_id, token_cost=0.12, compute_seconds=3, tool_calls=2)
    print(f"  [4] Budget       : {budget.budget_id} (used $0.12/$1.00)")

    # 5. Authorize
    trace_id = gw.new_trace()
    passed, results = gw.authorize_execute(
        token_id             = tok.token_id,
        work_contract_id     = wc.work_contract_id,
        requested_capability = "backend_impl",
        agent_id             = AGENT,
        operation_type       = "read_file",
        consent_grant_ref    = cr.consent_id,
        budget_id            = budget.budget_id,
        policy_context       = {"contract_hash": make_contract_hash(CONTRACT_KEY)},
        trace_id             = trace_id,
    )
    print(f"\n  [5] Authorize    : {'PASS' if passed else 'FAIL'} (trace={trace_id})")
    for r in results:
        mark = f"{GREEN}OK  {RESET}" if r.passed else f"{RED}FAIL{RESET}"
        print(f"      {mark} {r.module:<20} {r.message[:60]}")

    # 6. Verify delivery
    ok, drift = gw.verify_delivery(
        objective            = "讀取原始碼並產出分析報告",
        objective_keywords   = ["原始碼", "分析報告"],
        deliverable_summary  = "已讀取 gaap_runtime.py 原始碼，產出分析報告如下",
        trace_id             = trace_id,
    )
    print(f"\n  [6] Drift check  : {'PASS' if ok else 'FAIL'} (drift_score={drift.details.get('drift_score')})")

    # 7. Trust update
    event = "task_completed" if passed and ok else "task_failed"
    new_score = trust.record_event(AGENT, event, task_id=TASK_ID)
    print(f"  [7] Trust update : {event} → score={new_score:.3f}")

    print(f"\n  {GREEN}Smoke test done. All state saved to {DATA_DIR}/{RESET}\n")


# ─────────────────────────────────────────────────────────────────────────────
# 主程式
# ─────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gaap_cli",
        description="GaaP Runtime CLI — 管理 Token / Consent / Reputation / Audit / Contract / Artifact",
    )
    p.add_argument("--data-dir", default=DATA_DIR, help=f"JSONL 資料目錄（預設: {DATA_DIR}）")
    sub = p.add_subparsers(dest="command", required=True)

    # status
    sub.add_parser("status", help="顯示所有 store 摘要")

    # tokens
    tok_p = sub.add_parser("tokens", help="列出所有 capability token")
    tok_p.add_argument("--filter-agent", metavar="AGENT_ID")

    # consents
    sub.add_parser("consents", help="列出所有 consent record")

    # reputation
    sub.add_parser("reputation", help="列出所有 agent 信任評分")

    # audit
    aud_p = sub.add_parser("audit", help="查看 audit log")
    aud_p.add_argument("--type",   choices=["span", "decision", "tool_call"])
    aud_p.add_argument("--module", help="過濾 module 名稱")
    aud_p.add_argument("--limit",  type=int, default=50)

    # contracts
    sub.add_parser("contracts", help="列出所有 WorkContract")

    # artifacts
    sub.add_parser("artifacts", help="列出所有 Artifact")

    # token issue / revoke
    tok_sub = sub.add_parser("token", help="Token 管理（issue / revoke）")
    tok_sub_s = tok_sub.add_subparsers(dest="token_cmd", required=True)

    issue_p = tok_sub_s.add_parser("issue", help="發放新 Token")
    issue_p.add_argument("--agent", required=True)
    issue_p.add_argument("--wc",    required=True, help="work_contract_id")
    issue_p.add_argument("--caps",  required=True, help="逗號分隔能力清單")
    issue_p.add_argument("--ttl",   type=int, default=300)

    rev_p = tok_sub_s.add_parser("revoke", help="撤銷 Token")
    rev_p.add_argument("--id",     required=True)
    rev_p.add_argument("--reason", default="")

    # consent request / grant / deny
    con_sub = sub.add_parser("consent", help="Consent 管理（request / grant / deny）")
    con_sub_s = con_sub.add_subparsers(dest="consent_cmd", required=True)

    req_p = con_sub_s.add_parser("request", help="請求同意")
    req_p.add_argument("--op",     required=True, help="operation_type")
    req_p.add_argument("--task",   default="")
    req_p.add_argument("--fields", default="", help="逗號分隔敏感欄位")

    gra_p = con_sub_s.add_parser("grant", help="授予同意")
    gra_p.add_argument("--id",     required=True)
    gra_p.add_argument("--by",     default="human")

    den_p = con_sub_s.add_parser("deny", help="拒絕同意")
    den_p.add_argument("--id",     required=True)
    den_p.add_argument("--reason", default="")

    # run-demo
    sub.add_parser("run-demo", help="執行 runtime smoke test 並寫入持久化資料")

    return p


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()

    global DATA_DIR
    DATA_DIR = args.data_dir

    dispatch = {
        "status":     cmd_status,
        "tokens":     cmd_tokens,
        "consents":   cmd_consents,
        "reputation": cmd_reputation,
        "audit":      cmd_audit,
        "contracts":  cmd_contracts,
        "artifacts":  cmd_artifacts,
        "run-demo":   cmd_run_demo,
    }

    if args.command in dispatch:
        dispatch[args.command](args)
    elif args.command == "token":
        {"issue": cmd_token_issue, "revoke": cmd_token_revoke}[args.token_cmd](args)
    elif args.command == "consent":
        {"request": cmd_consent_request, "grant": cmd_consent_grant, "deny": cmd_consent_deny}[args.consent_cmd](args)


if __name__ == "__main__":
    main()
