"""
tests/test_gaap_runtime.py — GaaP Runtime 單元測試

執行方式：
    pip install pytest
    pytest tests/test_gaap_runtime.py -v

覆蓋率報告：
    pip install pytest-cov
    pytest tests/test_gaap_runtime.py --cov=examples.gaap_runtime --cov-report=term-missing -v

對應 TASK-001 驗收條件：coverage >= 80%
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# 確保可以 import examples.gaap_runtime
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))

import pytest
from gaap_runtime import (
    ArtifactRegistry,
    CapabilityToken,
    ConsentGate,
    EphemeralTokenRegistry,
    EphemeralTokenValidator,
    GaaPGateway,
    GaaPPersistence,
    GaaPResult,
    ObservabilityTracer,
    PolicyGate,
    ResourceGuard,
    RollbackCoordinator,
    SemanticDriftDetector,
    TrustScoreEngine,
    WorkContractManager,
    build_gateway,
    make_contract_hash,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

CONTRACT_TEXT = "project:GaaP-test version:2.1.0"
CONTRACT_HASH = make_contract_hash(CONTRACT_TEXT)


@pytest.fixture
def registry():
    return EphemeralTokenRegistry()


@pytest.fixture
def tracer():
    return ObservabilityTracer()


@pytest.fixture
def consent(tracer):
    return ConsentGate(tracer=tracer)


@pytest.fixture
def trust(tracer):
    return TrustScoreEngine(tracer=tracer)


@pytest.fixture
def drift(tracer):
    return SemanticDriftDetector(tracer=tracer)


@pytest.fixture
def resources(tracer):
    return ResourceGuard(tracer=tracer)


@pytest.fixture
def rollback(tracer):
    return RollbackCoordinator(tracer=tracer)


@pytest.fixture
def policy(tracer):
    return PolicyGate(CONTRACT_HASH, tracer=tracer)


@pytest.fixture
def full_gateway():
    gw, registry, consent, trust, resources, rollback = build_gateway(
        contract_content=CONTRACT_TEXT, persist=False
    )
    return gw, registry, consent, trust, resources, rollback


# ═══════════════════════════════════════════════════════════════════════════════
# GaaPResult
# ═══════════════════════════════════════════════════════════════════════════════

class TestGaaPResult:
    def test_pass_str(self):
        r = GaaPResult(True, "TestMod", "OK")
        assert "[PASS]" in str(r)

    def test_fail_str(self):
        r = GaaPResult(False, "TestMod", "Fail")
        assert "[FAIL]" in str(r)

    def test_to_dict(self):
        r = GaaPResult(True, "Mod", "msg", {"k": "v"})
        d = r.to_dict()
        assert d["passed"] is True
        assert d["module"] == "Mod"
        assert d["details"] == {"k": "v"}


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Ephemeral Token
# ═══════════════════════════════════════════════════════════════════════════════

class TestEphemeralToken:
    def test_issue_and_validate(self, registry):
        tok = registry.issue("agent-A", "WC-001", ["read_file"], ttl_seconds=300)
        assert tok.token_id.startswith("tok-")
        assert not tok.is_expired()
        assert tok.ttl_seconds() > 0

    def test_expired_token(self, registry):
        tok = registry.issue("agent-A", "WC-001", ["read_file"], ttl_seconds=-1)
        assert tok.is_expired()
        v = EphemeralTokenValidator(registry)
        r = v.validate(tok.token_id, "WC-001", "read_file")
        assert not r.passed
        assert "過期" in r.message

    def test_valid_token(self, registry):
        tok = registry.issue("agent-A", "WC-001", ["backend_impl"], ttl_seconds=300)
        v   = EphemeralTokenValidator(registry)
        r   = v.validate(tok.token_id, "WC-001", "backend_impl")
        assert r.passed

    def test_revoked_token(self, registry):
        tok = registry.issue("agent-A", "WC-001", ["read_file"], ttl_seconds=300)
        registry.revoke(tok.token_id, reason="test revoke")
        v = EphemeralTokenValidator(registry)
        r = v.validate(tok.token_id, "WC-001", "read_file")
        assert not r.passed
        assert "撤銷" in r.message

    def test_wrong_work_contract(self, registry):
        tok = registry.issue("agent-A", "WC-001", ["read_file"], ttl_seconds=300)
        v   = EphemeralTokenValidator(registry)
        r   = v.validate(tok.token_id, "WC-WRONG", "read_file")
        assert not r.passed
        assert "WorkContract" in r.message

    def test_capability_not_in_scope(self, registry):
        tok = registry.issue("agent-A", "WC-001", ["read_file"], ttl_seconds=300)
        v   = EphemeralTokenValidator(registry)
        r   = v.validate(tok.token_id, "WC-001", "delete_data")
        assert not r.passed
        assert "授權範圍" in r.message

    def test_nonexistent_token(self, registry):
        v = EphemeralTokenValidator(registry)
        r = v.validate("tok-NOTFOUND", "WC-001", "read_file")
        assert not r.passed
        assert "不存在" in r.message

    def test_token_rotation(self, registry):
        tok  = registry.issue("agent-A", "WC-001", ["read_file"], ttl_seconds=300)
        new_tok = registry.rotate(tok.token_id, ttl_seconds=300)
        assert new_tok is not None
        assert new_tok.token_id != tok.token_id
        assert new_tok.rotation_count == 1
        # 原 token 已撤銷
        assert registry.get(tok.token_id).revoked

    def test_active_tokens_for_agent(self, registry):
        registry.issue("agent-B", "WC-001", ["read_file"], ttl_seconds=300)
        registry.issue("agent-B", "WC-001", ["write_file"], ttl_seconds=300)
        assert len(registry.active_tokens_for("agent-B")) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Consent Gate
# ═══════════════════════════════════════════════════════════════════════════════

class TestConsentGate:
    def test_non_sensitive_operation(self, consent):
        r = consent.check("read_file", None)
        assert r.passed
        assert "不屬於敏感操作" in r.message

    def test_sensitive_no_consent_ref(self, consent):
        r = consent.check("credential_access", None)
        assert not r.passed
        assert "consent_grant_ref" in r.message

    def test_sensitive_nonexistent_consent(self, consent):
        r = consent.check("credential_access", "consent-FAKE")
        assert not r.passed
        assert "不存在" in r.message

    def test_grant_and_check(self, consent):
        cr = consent.request_consent("credential_access", ["api_key"], "T-001")
        consent.grant(cr.consent_id, "human@test.com")
        r = consent.check("credential_access", cr.consent_id)
        assert r.passed
        assert cr.granted_by == "human@test.com"

    def test_denied_consent(self, consent):
        cr = consent.request_consent("payment_operation", ["card_no"], "T-002")
        consent.deny(cr.consent_id, reason="security policy")
        r = consent.check("payment_operation", cr.consent_id)
        assert not r.passed
        assert "被拒絕" in r.message

    def test_expired_consent(self, consent):
        # 先 grant，再把 expires_at 設成過去以模擬過期
        cr = consent.request_consent("credential_access", ["key"], "T-003", ttl_seconds=3600)
        consent.grant(cr.consent_id, "human")
        assert cr.status == "granted"
        # 強制設定 expires_at 到過去
        import time as _time
        cr.expires_at = _time.time() - 1
        r = consent.check("credential_access", cr.consent_id)
        assert not r.passed
        assert "過期" in r.message

    def test_audit_trail(self, consent):
        cr = consent.request_consent("credential_access", ["key"], "T-004")
        consent.grant(cr.consent_id, "alice")
        assert any(e["event"] == "requested" for e in cr.audit_trail)
        assert any(e["event"] == "granted"   for e in cr.audit_trail)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Trust Score Engine
# ═══════════════════════════════════════════════════════════════════════════════

class TestTrustScoreEngine:
    def test_default_score(self, trust):
        s = trust.get_or_create("new-agent")
        assert s.trust_score == pytest.approx(0.7)
        assert s.tier() == "standard"

    def test_task_completed_gains(self, trust):
        for _ in range(5):
            trust.record_event("agent-x", "task_completed")
        s = trust.get_or_create("agent-x")
        assert s.trust_score > 0.7

    def test_policy_violation_deducts(self, trust):
        trust.record_event("agent-y", "policy_violation")
        s = trust.get_or_create("agent-y")
        assert s.trust_score < 0.7

    def test_multiple_violations_to_sandbox(self, trust):
        for _ in range(4):
            trust.record_event("bad-agent", "policy_violation")
        s = trust.get_or_create("bad-agent")
        assert s.tier() == "sandbox_only"

    def test_score_bounded(self, trust):
        for _ in range(100):
            trust.record_event("super-agent", "task_completed")
        s = trust.get_or_create("super-agent")
        assert s.trust_score <= 1.0

    def test_check_capability_pass(self, trust):
        r = trust.check_capability("agent-z", required_tier="standard")
        assert r.passed

    def test_check_capability_fail(self, trust):
        for _ in range(4):
            trust.record_event("low-agent", "consent_violation")
        r = trust.check_capability("low-agent", required_tier="standard")
        assert not r.passed
        assert "低於要求" in r.message

    def test_score_history_recorded(self, trust):
        trust.record_event("hist-agent", "task_completed", task_id="T-1")
        s = trust.get_or_create("hist-agent")
        assert len(s.score_history) >= 1
        assert s.score_history[-1]["reason"] == "task_completed"

    def test_decay_all(self, trust):
        trust.record_event("decay-agent", "task_completed")
        before = trust.get_or_create("decay-agent").trust_score
        trust.decay_all(rate_per_day=0.01, floor=0.1)
        after = trust.get_or_create("decay-agent").trust_score
        assert after <= before


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Semantic Drift Detector
# ═══════════════════════════════════════════════════════════════════════════════

class TestSemanticDriftDetector:
    def test_perfect_alignment(self, drift):
        r = drift.detect(
            objective            = "新增單元測試，coverage >= 80%",
            objective_keywords   = ["單元測試", "coverage", "80%"],
            deliverable_summary  = "新增了單元測試，coverage=85%，80%的閾值已達到",
            metric_thresholds    = {"coverage": 80},
            actual_metrics       = {"coverage": 85},
        )
        assert r.passed
        assert r.details["drift_score"] == pytest.approx(0.0)

    def test_full_drift_auto_rejected(self, drift):
        r = drift.detect(
            objective            = "新增單元測試，coverage >= 80%",
            objective_keywords   = ["單元測試", "coverage", "80%"],
            deliverable_summary  = "更新了 README 文件，添加了使用說明",
            metric_thresholds    = {"coverage": 80},
            actual_metrics       = {"coverage": 0},
            forbidden_changes_detected=True,
        )
        assert not r.passed
        assert r.details["drift_score"] > 0.4

    def test_flag_range(self, drift):
        r = drift.detect(
            objective            = "A B C D E",
            objective_keywords   = ["A", "B", "C", "D", "E"],
            deliverable_summary  = "A B",   # 只覆蓋 2/5
        )
        assert r.details["drift_score"] > 0.15
        # 可能是 flag 或 auto_rejected，取決於 score

    def test_forbidden_change_impact(self, drift):
        r1 = drift.detect("obj", ["k"], "k", forbidden_changes_detected=False)
        r2 = drift.detect("obj", ["k"], "k", forbidden_changes_detected=True)
        assert r1.details["drift_score"] < r2.details["drift_score"]

    def test_missing_keywords_in_details(self, drift):
        r = drift.detect(
            objective            = "test",
            objective_keywords   = ["A", "B", "C"],
            deliverable_summary  = "A done",
        )
        missing = r.details["missing_keywords"]
        assert "B" in missing
        assert "C" in missing


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Rollback Coordinator
# ═══════════════════════════════════════════════════════════════════════════════

class TestRollbackCoordinator:
    def test_register_and_execute(self, rollback):
        rollback.register_snapshot("agent-A", "snap-001")
        plan = rollback.initiate("WC-001", "task_failed", ["agent-A"])
        r    = rollback.execute(plan.rollback_id)
        assert r.passed
        assert plan.status == "completed"

    def test_execute_no_snapshot(self, rollback):
        plan = rollback.initiate("WC-001", "task_failed", ["no-snap-agent"])
        r    = rollback.execute(plan.rollback_id)
        assert not r.passed
        assert plan.status == "partially_completed"

    def test_nonexistent_plan(self, rollback):
        r = rollback.execute("rb-NOTFOUND")
        assert not r.passed

    def test_partial_rollback(self, rollback):
        rollback.register_snapshot("agent-A", "snap-A")
        plan = rollback.initiate("WC-001", "drift_auto_rejected",
                                 ["agent-A", "agent-B"], strategy="partial_rollback")
        r = rollback.execute(plan.rollback_id)
        assert plan.strategy == "partial_rollback"
        assert "agent-A" in str(r.details)

    def test_completed_at_set(self, rollback):
        rollback.register_snapshot("a", "snap")
        plan = rollback.initiate("WC", "task_failed", ["a"])
        rollback.execute(plan.rollback_id)
        assert plan.completed_at is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Resource Guard
# ═══════════════════════════════════════════════════════════════════════════════

class TestResourceGuard:
    def test_within_budget(self, resources):
        b = resources.create_budget("T-001", token_cost_ceiling=2.0, compute_budget_seconds=300)
        resources.record_usage(b.budget_id, token_cost=0.5, compute_seconds=10)
        r = resources.check(b.budget_id)
        assert r.passed

    def test_token_cost_exceeded(self, resources):
        b = resources.create_budget("T-002", token_cost_ceiling=0.50)
        resources.record_usage(b.budget_id, token_cost=3.27)
        r = resources.check(b.budget_id)
        assert not r.passed
        assert "token_cost" in r.message

    def test_compute_exceeded(self, resources):
        b = resources.create_budget("T-003", compute_budget_seconds=60)
        resources.record_usage(b.budget_id, compute_seconds=90)
        r = resources.check(b.budget_id)
        assert not r.passed

    def test_tool_calls_exceeded(self, resources):
        b = resources.create_budget("T-004", tool_calls_max=5)
        resources.record_usage(b.budget_id, tool_calls=10)
        r = resources.check(b.budget_id)
        assert not r.passed

    def test_overflow_events_recorded(self, resources):
        b = resources.create_budget("T-005", token_cost_ceiling=0.1)
        resources.record_usage(b.budget_id, token_cost=1.0)
        resources.check(b.budget_id)
        assert len(b.overflow_events) >= 1

    def test_nonexistent_budget(self, resources):
        r = resources.check("budget-NOTFOUND")
        assert not r.passed

    def test_cumulative_usage(self, resources):
        b = resources.create_budget("T-006", tool_calls_max=10)
        for _ in range(4):
            resources.record_usage(b.budget_id, tool_calls=2)
        assert b.tool_calls_used == 8


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Policy Gate
# ═══════════════════════════════════════════════════════════════════════════════

class TestPolicyGate:
    def test_valid_policy(self, policy):
        r = policy.check({"contract_hash": CONTRACT_HASH})
        assert r.passed

    def test_invalid_hash(self, policy):
        r = policy.check({"contract_hash": "sha256:WRONG"})
        assert not r.passed
        assert "contract_hash" in r.message

    def test_invariant_violation(self, policy):
        r = policy.check({
            "contract_hash": CONTRACT_HASH,
            "violated_invariants": ["INV-API-001"],
        })
        assert not r.passed
        assert "INV-API-001" in r.details.get("violated", [])

    def test_unknown_invariant_not_blocked(self, policy):
        r = policy.check({
            "contract_hash": CONTRACT_HASH,
            "violated_invariants": ["INV-UNKNOWN-999"],
        })
        assert r.passed


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Persistence
# ═══════════════════════════════════════════════════════════════════════════════

class TestPersistence:
    def test_append_and_load(self, tmp_path):
        p = GaaPPersistence(tmp_path)
        p.append("tokens", {"token_id": "tok-001", "agent_id": "a"})
        p.append("tokens", {"token_id": "tok-002", "agent_id": "b"})
        records = p.load_all("tokens")
        assert len(records) == 2
        assert records[0]["token_id"] == "tok-001"

    def test_snapshot_latest(self, tmp_path):
        p = GaaPPersistence(tmp_path)
        p.append("tokens", {"token_id": "tok-001", "revoked": False})
        p.append("tokens", {"token_id": "tok-001", "revoked": True})   # 更新
        snap = p.snapshot_latest("tokens", "token_id")
        assert snap["tok-001"]["revoked"] is True

    def test_empty_store(self, tmp_path):
        p = GaaPPersistence(tmp_path)
        assert p.load_all("tokens") == []

    def test_token_registry_persists(self, tmp_path):
        p   = GaaPPersistence(tmp_path)
        reg = EphemeralTokenRegistry(p)
        tok = reg.issue("agent-A", "WC-001", ["read_file"], ttl_seconds=300)

        # 重建 registry，應從磁碟讀取
        reg2 = EphemeralTokenRegistry(p)
        assert reg2.get(tok.token_id) is not None

    def test_consent_persists(self, tmp_path):
        p  = GaaPPersistence(tmp_path)
        cg = ConsentGate(p)
        cr = cg.request_consent("credential_access", ["key"], "T-1")
        cg.grant(cr.consent_id)

        cg2 = ConsentGate(p)
        assert cg2.get(cr.consent_id) is not None
        assert cg2.get(cr.consent_id).status == "granted"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. ObservabilityTracer
# ═══════════════════════════════════════════════════════════════════════════════

class TestObservabilityTracer:
    def test_new_trace(self, tracer):
        tid = tracer.new_trace()
        assert tid.startswith("trace-")

    def test_start_end_span(self, tracer):
        tid  = tracer.new_trace()
        span = tracer.start_span("test_op", tid)
        assert span.span_id.startswith("span-")
        tracer.end_span(span)
        assert span.ended_at is not None
        assert span.duration_ms() is not None

    def test_log_decision(self, tracer):
        tracer.log_decision("Mod", "action", "reason", True, trace_id="t1")
        log = tracer.get_decision_log()
        assert len(log) == 1
        assert log[0]["module"] == "Mod"
        assert log[0]["result"] is True

    def test_audit_tool_call(self, tracer):
        tracer.audit_tool_call("read_file", {"path": "/foo"}, span_id="s1")
        audit = tracer.get_tool_audit()
        assert len(audit) == 1
        assert audit[0]["tool"] == "read_file"
        assert "sha256:" in audit[0]["input_hash"]

    def test_export_jsonl(self, tracer):
        tid  = tracer.new_trace()
        span = tracer.start_span("op", tid)
        tracer.end_span(span)
        tracer.log_decision("M", "d", "r", True)
        data = tracer.export_jsonl()
        types = {d["_type"] for d in data}
        assert "span"     in types
        assert "decision" in types


# ═══════════════════════════════════════════════════════════════════════════════
# 10. WorkContractManager
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkContractManager:
    def test_create_and_validate(self):
        mgr = WorkContractManager()
        wc  = mgr.create(
            owner_capabilities    = {"caps": ["orchestrate"]},
            consumer_capabilities = {"caps": ["code_review"]},
            scope_ref             = "TASK-001",
            parties               = ["owner-agent", "code-agent"],
        )
        r = mgr.validate(wc.work_contract_id)
        assert r.passed

    def test_hash_is_deterministic(self):
        mgr = WorkContractManager()
        wc1 = mgr.create({"caps": ["A"]}, {"caps": ["B"]}, "T-1", ["x", "y"])
        wc2 = mgr.create({"caps": ["A"]}, {"caps": ["B"]}, "T-1", ["x", "y"])
        assert wc1.contract_hash == wc2.contract_hash

    def test_validate_nonexistent(self):
        mgr = WorkContractManager()
        r   = mgr.validate("WC-NOTFOUND")
        assert not r.passed

    def test_close_contract(self):
        mgr = WorkContractManager()
        wc  = mgr.create({}, {}, "T-2", ["a"])
        mgr.close(wc.work_contract_id)
        r = mgr.validate(wc.work_contract_id)
        assert not r.passed
        assert "關閉" in r.message

    def test_persists(self, tmp_path):
        p   = GaaPPersistence(tmp_path)
        mgr = WorkContractManager(p)
        wc  = mgr.create({"x": 1}, {"y": 2}, "scope", ["a", "b"])
        mgr2 = WorkContractManager(p)
        assert mgr2.get(wc.work_contract_id) is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 11. ArtifactRegistry
# ═══════════════════════════════════════════════════════════════════════════════

class TestArtifactRegistry:
    def test_register_and_verify(self):
        ar = ArtifactRegistry()
        ar.register("art-001", "content body", "/path/to/art", "spec", "trusted")
        r  = ar.verify("art-001")
        assert r.passed

    def test_content_hash_check(self):
        ar = ArtifactRegistry()
        a  = ar.register("art-002", "hello", "/x", "spec")
        r  = ar.verify("art-002", expected_hash=a.content_hash)
        assert r.passed
        r2 = ar.verify("art-002", expected_hash="sha256:WRONG")
        assert not r2.passed

    def test_untrusted_artifact(self):
        ar = ArtifactRegistry()
        ar.register("art-003", "data", "/x", "spec", trust="untrusted")
        r  = ar.verify("art-003")
        assert not r.passed
        assert "untrusted" in r.message

    def test_provenance_chain(self):
        ar = ArtifactRegistry()
        ar.register("art-A", "base",  "/a", "spec", lineage=[])
        ar.register("art-B", "layer", "/b", "spec", lineage=["art-A"])
        ar.register("art-C", "top",   "/c", "spec", lineage=["art-B"])
        chain = ar.get_provenance_chain("art-C")
        ids   = [c["artifact_id"] for c in chain]
        assert "art-A" in ids
        assert "art-B" in ids
        assert "art-C" in ids

    def test_nonexistent_artifact(self):
        ar = ArtifactRegistry()
        r  = ar.verify("art-NOTFOUND")
        assert not r.passed


# ═══════════════════════════════════════════════════════════════════════════════
# 12. GaaPGateway（整合測試）
# ═══════════════════════════════════════════════════════════════════════════════

class TestGaaPGateway:
    def _setup(self):
        gw, registry, consent, trust, resources, rollback = build_gateway(
            contract_content=CONTRACT_TEXT, persist=False
        )
        AGENT   = "test-agent"
        WC_ID   = "WC-GATE-001"
        TASK_ID = "T-GW-001"

        tok = registry.issue(AGENT, WC_ID, ["backend_impl", "read_file"], ttl_seconds=300, task_id=TASK_ID)
        cr  = consent.request_consent("read_file", ["source"], TASK_ID)
        consent.consent._consents[cr.consent_id].status     = "granted"
        consent.consent._consents[cr.consent_id].granted_by = "human"
        cr.status     = "granted"
        cr.granted_by = "human"
        budget = resources.create_budget(TASK_ID, token_cost_ceiling=2.0, compute_budget_seconds=300)
        return gw, tok, cr, budget, AGENT, WC_ID

    def test_full_authorize_pass(self, full_gateway):
        gw, registry, consent_gate, trust, resources, rollback = full_gateway
        AGENT   = "ga-agent"
        TASK_ID = "T-GA-001"

        # 建立 WorkContract（build_gateway 已配置 WorkContractManager）
        wc = gw.contracts.create(
            {"caps": ["orchestrate"]}, {"caps": ["backend_impl"]},
            TASK_ID, [AGENT, "orchestrator"]
        )
        WC_ID = wc.work_contract_id

        tok    = registry.issue(AGENT, WC_ID, ["backend_impl"], ttl_seconds=300)
        cr     = consent_gate.request_consent("read_file", ["src"], TASK_ID)
        consent_gate.grant(cr.consent_id, "human")
        budget = resources.create_budget(TASK_ID, token_cost_ceiling=2.0)

        passed, results = gw.authorize_execute(
            token_id             = tok.token_id,
            work_contract_id     = WC_ID,
            requested_capability = "backend_impl",
            agent_id             = AGENT,
            operation_type       = "read_file",
            consent_grant_ref    = cr.consent_id,
            budget_id            = budget.budget_id,
            policy_context       = {"contract_hash": CONTRACT_HASH},
        )
        assert passed, [str(r) for r in results if not r.passed]
        assert all(r.passed for r in results)

    def test_authorize_fail_expired_token(self, full_gateway):
        gw, registry, consent_gate, trust, resources, rollback = full_gateway
        AGENT   = "exp-agent"
        TASK_ID = "T-EXP-001"

        # 建立 WorkContract
        wc = gw.contracts.create({}, {}, TASK_ID, [AGENT])
        WC_ID = wc.work_contract_id

        tok    = registry.issue(AGENT, WC_ID, ["backend_impl"], ttl_seconds=-1)
        cr     = consent_gate.request_consent("read_file", ["src"], TASK_ID)
        consent_gate.grant(cr.consent_id)
        budget = resources.create_budget(TASK_ID)

        passed, results = gw.authorize_execute(
            token_id             = tok.token_id,
            work_contract_id     = WC_ID,
            requested_capability = "backend_impl",
            agent_id             = AGENT,
            operation_type       = "read_file",
            consent_grant_ref    = cr.consent_id,
            budget_id            = budget.budget_id,
            policy_context       = {"contract_hash": CONTRACT_HASH},
        )
        assert not passed
        failed_modules = [r.module for r in results if not r.passed]
        assert "EphemeralToken" in failed_modules

    def test_verify_delivery_pass(self, full_gateway):
        gw = full_gateway[0]
        ok, r = gw.verify_delivery(
            objective            = "新增測試，coverage >= 80%",
            objective_keywords   = ["測試", "coverage", "80%"],
            deliverable_summary  = "新增了測試，coverage=85%，超過80%門檻",
            metric_thresholds    = {"coverage": 80},
            actual_metrics       = {"coverage": 85},
        )
        assert ok
        assert r.details["drift_score"] == pytest.approx(0.0)

    def test_verify_delivery_fail_drift(self, full_gateway):
        gw = full_gateway[0]
        ok, r = gw.verify_delivery(
            objective            = "新增測試",
            objective_keywords   = ["測試", "coverage", "80%"],
            deliverable_summary  = "更新了文件說明",
            metric_thresholds    = {"coverage": 80},
            actual_metrics       = {"coverage": 0},
            forbidden_changes_detected=True,
        )
        assert not ok
        assert r.details["drift_score"] > 0.4

    def test_new_trace_returns_string(self, full_gateway):
        gw = full_gateway[0]
        tid = gw.new_trace()
        assert isinstance(tid, str)
        assert len(tid) > 0

    def test_build_gateway_factory(self):
        gw, reg, cg, te, rg, rc = build_gateway(CONTRACT_TEXT, persist=False)
        assert gw is not None
        assert reg is not None
        assert cg  is not None
