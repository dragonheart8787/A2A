"""
gaap_runtime.py — GaaP 執行期治理核心函式庫

實作七大 GaaP 模組的執行期邏輯：
  1. EphemeralTokenValidator   — 短命限域令牌驗證
  2. ConsentGate               — 明確同意閘門
  3. TrustScoreEngine          — Agent 信任評分
  4. SemanticDriftDetector     — 語意漂移偵測
  5. RollbackCoordinator       — 多代理回滾協調
  6. ResourceGuard             — 資源成本治理
  7. PolicyGate                — Policy-as-Code 閘門

這是真正可跑的 Python 執行期，不是規格。
可直接 import 使用，或執行 demo_full_flow.py。
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# 共用資料結構
# ---------------------------------------------------------------------------

@dataclass
class GaaPResult:
    passed: bool
    module: str
    message: str
    details: dict = field(default_factory=dict)

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.module}: {self.message}"


# ---------------------------------------------------------------------------
# 1. Ephemeral Scoped Capability Token（短命限域令牌）
# ---------------------------------------------------------------------------

@dataclass
class CapabilityToken:
    token_id: str
    agent_id: str
    work_contract_id: str
    scoped_capabilities: list[str]
    issued_at: float          # unix timestamp
    expires_at: float         # unix timestamp
    revoked: bool = False
    task_id: str | None = None


class EphemeralTokenRegistry:
    """In-memory token registry（production 應持久化）"""

    def __init__(self) -> None:
        self._tokens: dict[str, CapabilityToken] = {}

    def issue(
        self,
        agent_id: str,
        work_contract_id: str,
        scoped_capabilities: list[str],
        ttl_seconds: int = 300,
        task_id: str | None = None,
    ) -> CapabilityToken:
        now = time.time()
        token = CapabilityToken(
            token_id=f"tok-{uuid.uuid4().hex[:12]}",
            agent_id=agent_id,
            work_contract_id=work_contract_id,
            scoped_capabilities=scoped_capabilities,
            issued_at=now,
            expires_at=now + ttl_seconds,
            task_id=task_id,
        )
        self._tokens[token.token_id] = token
        return token

    def revoke(self, token_id: str, reason: str = "") -> None:
        if token_id in self._tokens:
            self._tokens[token_id].revoked = True

    def get(self, token_id: str) -> CapabilityToken | None:
        return self._tokens.get(token_id)


class EphemeralTokenValidator:
    """模組 1：驗證短命限域令牌"""

    def __init__(self, registry: EphemeralTokenRegistry) -> None:
        self.registry = registry

    def validate(
        self,
        token_id: str,
        work_contract_id: str,
        requested_capability: str,
    ) -> GaaPResult:
        module = "EphemeralToken"
        token = self.registry.get(token_id)

        if token is None:
            return GaaPResult(False, module, f"Token {token_id!r} 不存在")

        if token.revoked:
            return GaaPResult(False, module, f"Token {token_id!r} 已被撤銷")

        now = time.time()
        if now > token.expires_at:
            remaining = token.expires_at - now
            return GaaPResult(
                False, module,
                f"Token 已過期 {abs(remaining):.0f} 秒",
                {"expired_at": datetime.fromtimestamp(token.expires_at, tz=timezone.utc).isoformat()},
            )

        if token.work_contract_id != work_contract_id:
            return GaaPResult(
                False, module,
                f"Token 綁定的 WorkContract {token.work_contract_id!r} 與請求的 {work_contract_id!r} 不符",
            )

        if requested_capability not in token.scoped_capabilities:
            return GaaPResult(
                False, module,
                f"能力 {requested_capability!r} 不在此 Token 的授權範圍內 {token.scoped_capabilities}",
            )

        ttl_left = token.expires_at - now
        return GaaPResult(
            True, module,
            f"Token 有效（剩餘 {ttl_left:.0f} 秒，能力 {requested_capability!r} 已授權）",
            {"ttl_left_seconds": ttl_left, "agent_id": token.agent_id},
        )


# ---------------------------------------------------------------------------
# 2. Consent Gate（明確同意閘門）
# ---------------------------------------------------------------------------

SENSITIVE_OPERATIONS = {
    "read_sensitive_data", "write_sensitive_data", "delete_data",
    "external_api_call", "credential_access", "payment_operation",
    "identity_verification", "cross_agent_data_share",
    "file_system_write", "code_execution",
}


@dataclass
class ConsentRecord:
    consent_id: str
    operation_type: str
    sensitive_fields: list[str]
    status: str   # pending / granted / denied
    granted_by: str | None = None
    granted_at: float | None = None


class ConsentGate:
    """模組 2：同意閘門，敏感操作必須先取得明確同意"""

    def __init__(self) -> None:
        self._consents: dict[str, ConsentRecord] = {}

    def request_consent(
        self,
        operation_type: str,
        sensitive_fields: list[str],
        task_id: str,
    ) -> ConsentRecord:
        record = ConsentRecord(
            consent_id=f"consent-{uuid.uuid4().hex[:8]}",
            operation_type=operation_type,
            sensitive_fields=sensitive_fields,
            status="pending",
        )
        self._consents[record.consent_id] = record
        return record

    def grant(self, consent_id: str, granted_by: str = "human") -> None:
        if consent_id in self._consents:
            r = self._consents[consent_id]
            r.status = "granted"
            r.granted_by = granted_by
            r.granted_at = time.time()

    def deny(self, consent_id: str) -> None:
        if consent_id in self._consents:
            self._consents[consent_id].status = "denied"

    def check(self, operation_type: str, consent_grant_ref: str | None) -> GaaPResult:
        module = "ConsentGate"

        if operation_type not in SENSITIVE_OPERATIONS:
            return GaaPResult(True, module, f"操作 {operation_type!r} 不需要同意")

        if not consent_grant_ref:
            return GaaPResult(
                False, module,
                f"敏感操作 {operation_type!r} 缺少 consent_grant_ref；必須先取得同意",
                {"required_from": "human", "operation": operation_type},
            )

        record = self._consents.get(consent_grant_ref)
        if record is None:
            return GaaPResult(
                False, module,
                f"consent_grant_ref {consent_grant_ref!r} 不存在於 registry",
            )

        if record.status == "denied":
            return GaaPResult(False, module, f"同意已被拒絕（consent_id={consent_grant_ref}）")

        if record.status != "granted":
            return GaaPResult(
                False, module,
                f"同意尚未授予（狀態={record.status}）；請等待授權",
            )

        return GaaPResult(
            True, module,
            f"同意已授予（由 {record.granted_by!r}，操作 {operation_type!r}）",
            {"consent_id": consent_grant_ref, "granted_by": record.granted_by},
        )


# ---------------------------------------------------------------------------
# 3. Trust Score Engine（Agent 信任評分）
# ---------------------------------------------------------------------------

@dataclass
class AgentScore:
    agent_id: str
    trust_score: float = 0.7
    tasks_completed: int = 0
    tasks_failed: int = 0
    policy_violations: int = 0
    drift_incidents: int = 0
    consent_violations: int = 0
    rollback_triggered: int = 0

    def tier(self) -> str:
        if self.trust_score >= 0.8:
            return "full"
        elif self.trust_score >= 0.6:
            return "standard"
        elif self.trust_score >= 0.4:
            return "restricted"
        else:
            return "sandbox_only"


class TrustScoreEngine:
    """模組 3：動態信任評分，歷史績效決定能力授予層級"""

    DELTAS = {
        "task_completed":    +0.02,
        "task_failed":       -0.05,
        "policy_violation":  -0.15,
        "drift_incident":    -0.08,
        "consent_violation": -0.20,
        "rollback_triggered":-0.10,
    }
    MAX_GAIN_PER_TASK = 0.05
    FLOOR = 0.0
    CEILING = 1.0

    def __init__(self) -> None:
        self._agents: dict[str, AgentScore] = {}

    def get_or_create(self, agent_id: str) -> AgentScore:
        if agent_id not in self._agents:
            self._agents[agent_id] = AgentScore(agent_id=agent_id)
        return self._agents[agent_id]

    def record_event(self, agent_id: str, event: str) -> None:
        score = self.get_or_create(agent_id)
        delta = self.DELTAS.get(event, 0.0)
        if event == "task_completed":
            delta = min(delta, self.MAX_GAIN_PER_TASK)
        score.trust_score = max(self.FLOOR, min(self.CEILING, score.trust_score + delta))
        if hasattr(score, event):
            setattr(score, event, getattr(score, event) + 1)

    def check_capability(self, agent_id: str, required_tier: str = "standard") -> GaaPResult:
        module = "TrustScore"
        score = self.get_or_create(agent_id)
        tier_order = ["sandbox_only", "restricted", "standard", "full"]
        agent_tier = score.tier()

        if tier_order.index(agent_tier) < tier_order.index(required_tier):
            return GaaPResult(
                False, module,
                f"Agent {agent_id!r} 信任分數 {score.trust_score:.2f}（{agent_tier} tier），"
                f"低於要求 {required_tier} tier",
                {"trust_score": score.trust_score, "tier": agent_tier},
            )

        return GaaPResult(
            True, module,
            f"Agent {agent_id!r} 信任分數 {score.trust_score:.2f}（{agent_tier} tier），通過",
            {"trust_score": score.trust_score, "tier": agent_tier},
        )


# ---------------------------------------------------------------------------
# 4. Semantic Drift Detector（語意漂移偵測）
# ---------------------------------------------------------------------------

class SemanticDriftDetector:
    """模組 4：比對 deliverable 與 objective 的語意對齊度"""

    AUTO_REJECT_THRESHOLD = 0.40
    FLAG_THRESHOLD = 0.15

    def detect(
        self,
        objective: str,
        objective_keywords: list[str],
        deliverable_summary: str,
        metric_thresholds: dict[str, float] | None = None,
        actual_metrics: dict[str, float] | None = None,
        forbidden_changes_detected: bool = False,
    ) -> GaaPResult:
        module = "SemanticDrift"

        # 關鍵詞覆蓋率（40% 權重）
        deliverable_lower = deliverable_summary.lower()
        covered = [kw for kw in objective_keywords if kw.lower() in deliverable_lower]
        missing = [kw for kw in objective_keywords if kw.lower() not in deliverable_lower]
        coverage_ratio = len(covered) / len(objective_keywords) if objective_keywords else 1.0

        # 指標達標率（40% 權重）
        metric_pass_ratio = 1.0
        failed_metrics: list[str] = []
        if metric_thresholds and actual_metrics:
            checks = []
            for key, threshold in metric_thresholds.items():
                actual = actual_metrics.get(key, 0.0)
                passed = actual >= threshold
                checks.append(passed)
                if not passed:
                    failed_metrics.append(f"{key}: actual={actual} < threshold={threshold}")
            metric_pass_ratio = sum(checks) / len(checks) if checks else 1.0

        # 禁止變更偵測（20% 權重）
        forbidden_penalty = 0.0 if not forbidden_changes_detected else 1.0

        # 合成 drift score（越高越偏離）
        drift_score = 1.0 - (
            coverage_ratio * 0.4
            + metric_pass_ratio * 0.4
            + (1.0 - forbidden_penalty) * 0.2
        )
        drift_score = round(max(0.0, min(1.0, drift_score)), 3)

        details = {
            "drift_score": drift_score,
            "keyword_coverage": f"{len(covered)}/{len(objective_keywords)}",
            "missing_keywords": missing,
            "failed_metrics": failed_metrics,
            "forbidden_changes": forbidden_changes_detected,
        }

        if drift_score > self.AUTO_REJECT_THRESHOLD:
            return GaaPResult(
                False, module,
                f"語意漂移過高（drift_score={drift_score:.3f} > {self.AUTO_REJECT_THRESHOLD}），自動拒絕",
                details,
            )
        elif drift_score > self.FLAG_THRESHOLD:
            return GaaPResult(
                True, module,
                f"語意漂移警告（drift_score={drift_score:.3f}），建議人工審核",
                {**details, "status": "flag"},
            )
        else:
            return GaaPResult(
                True, module,
                f"語意對齊良好（drift_score={drift_score:.3f}），通過",
                {**details, "status": "pass"},
            )


# ---------------------------------------------------------------------------
# 5. Rollback Coordinator（多代理回滾）
# ---------------------------------------------------------------------------

@dataclass
class RollbackPlan:
    rollback_id: str
    work_contract_id: str
    trigger: str
    strategy: str
    participants: list[dict]
    status: str = "planned"


class RollbackCoordinator:
    """模組 5：協調多代理回滾"""

    def __init__(self) -> None:
        self._snapshots: dict[str, str] = {}   # agent_id -> snapshot_ref
        self._plans: dict[str, RollbackPlan] = {}

    def register_snapshot(self, agent_id: str, snapshot_ref: str) -> None:
        self._snapshots[agent_id] = snapshot_ref

    def initiate(
        self,
        work_contract_id: str,
        trigger: str,
        affected_agents: list[str],
        strategy: str = "partial_rollback",
    ) -> RollbackPlan:
        participants = []
        for agent_id in affected_agents:
            snap = self._snapshots.get(agent_id, "NO_SNAPSHOT")
            participants.append({
                "agent_id": agent_id,
                "rollback_action": "restore_snapshot" if snap != "NO_SNAPSHOT" else "notify_only",
                "snapshot_ref": snap,
                "status": "pending",
            })

        plan = RollbackPlan(
            rollback_id=f"rb-{uuid.uuid4().hex[:8]}",
            work_contract_id=work_contract_id,
            trigger=trigger,
            strategy=strategy,
            participants=participants,
        )
        self._plans[plan.rollback_id] = plan
        return plan

    def execute(self, rollback_id: str) -> GaaPResult:
        module = "RollbackCoord"
        plan = self._plans.get(rollback_id)
        if not plan:
            return GaaPResult(False, module, f"RollbackPlan {rollback_id!r} 不存在")

        results = []
        for p in plan.participants:
            if p["snapshot_ref"] == "NO_SNAPSHOT":
                p["status"] = "failed"
                results.append(f"  {p['agent_id']}: 無快照，無法還原")
            else:
                p["status"] = "completed"
                results.append(f"  {p['agent_id']}: 已還原至 {p['snapshot_ref']}")

        failed = [p for p in plan.participants if p["status"] == "failed"]
        plan.status = "completed" if not failed else "partially_completed"

        return GaaPResult(
            not bool(failed), module,
            f"回滾 {rollback_id}（{plan.strategy}）{'完成' if not failed else '部分完成'}",
            {"participants": results, "status": plan.status},
        )


# ---------------------------------------------------------------------------
# 6. Resource Guard（資源成本治理）
# ---------------------------------------------------------------------------

@dataclass
class ResourceBudget:
    budget_id: str
    task_id: str
    token_cost_ceiling: float
    compute_budget_seconds: int
    tool_calls_max: int
    overflow_action: str = "terminate"
    # 實際用量（執行中更新）
    token_cost_actual: float = 0.0
    compute_seconds_used: int = 0
    tool_calls_used: int = 0


class ResourceGuard:
    """模組 6：追蹤資源用量，超限觸發 overflow_action"""

    def __init__(self) -> None:
        self._budgets: dict[str, ResourceBudget] = {}

    def create_budget(
        self,
        task_id: str,
        token_cost_ceiling: float = 2.0,
        compute_budget_seconds: int = 300,
        tool_calls_max: int = 50,
        overflow_action: str = "terminate",
    ) -> ResourceBudget:
        budget = ResourceBudget(
            budget_id=f"budget-{uuid.uuid4().hex[:8]}",
            task_id=task_id,
            token_cost_ceiling=token_cost_ceiling,
            compute_budget_seconds=compute_budget_seconds,
            tool_calls_max=tool_calls_max,
            overflow_action=overflow_action,
        )
        self._budgets[budget.budget_id] = budget
        return budget

    def record_usage(
        self,
        budget_id: str,
        token_cost: float = 0.0,
        compute_seconds: int = 0,
        tool_calls: int = 0,
    ) -> None:
        if budget_id in self._budgets:
            b = self._budgets[budget_id]
            b.token_cost_actual += token_cost
            b.compute_seconds_used += compute_seconds
            b.tool_calls_used += tool_calls

    def check(self, budget_id: str) -> GaaPResult:
        module = "ResourceGuard"
        budget = self._budgets.get(budget_id)
        if not budget:
            return GaaPResult(False, module, f"Budget {budget_id!r} 不存在")

        violations = []
        if budget.token_cost_actual > budget.token_cost_ceiling:
            violations.append(
                f"token_cost: {budget.token_cost_actual:.3f} > ceiling {budget.token_cost_ceiling}"
            )
        if budget.compute_seconds_used > budget.compute_budget_seconds:
            violations.append(
                f"compute: {budget.compute_seconds_used}s > budget {budget.compute_budget_seconds}s"
            )
        if budget.tool_calls_used > budget.tool_calls_max:
            violations.append(
                f"tool_calls: {budget.tool_calls_used} > max {budget.tool_calls_max}"
            )

        if violations:
            return GaaPResult(
                False, module,
                f"資源超限（overflow_action={budget.overflow_action}）：{'; '.join(violations)}",
                {
                    "violations": violations,
                    "actual": {
                        "token_cost": budget.token_cost_actual,
                        "compute_seconds": budget.compute_seconds_used,
                        "tool_calls": budget.tool_calls_used,
                    },
                },
            )

        return GaaPResult(
            True, module,
            f"資源用量正常（token={budget.token_cost_actual:.3f}/{budget.token_cost_ceiling}，"
            f"compute={budget.compute_seconds_used}s/{budget.compute_budget_seconds}s，"
            f"tool_calls={budget.tool_calls_used}/{budget.tool_calls_max}）",
        )


# ---------------------------------------------------------------------------
# 7. Policy Gate（Policy-as-Code 閘門）
# ---------------------------------------------------------------------------

class PolicyGate:
    """模組 7（原有）：Policy-as-Code，驗證 contract_hash + invariants"""

    def __init__(self, contract_hash: str, invariants: list[str] | None = None) -> None:
        self.contract_hash = contract_hash
        self.invariants = invariants or ["INV-API-001", "INV-MOD-002", "INV-DEP-003", "INV-BREAK-004"]

    def check(self, policy_context: dict) -> GaaPResult:
        module = "PolicyGate"
        incoming_hash = policy_context.get("contract_hash", "")

        if incoming_hash != self.contract_hash:
            return GaaPResult(
                False, module,
                f"Policy context 的 contract_hash 不符：expected={self.contract_hash!r}，got={incoming_hash!r}",
            )

        violated = []
        requested_violations = policy_context.get("violated_invariants", [])
        for inv in requested_violations:
            if inv in self.invariants:
                violated.append(inv)

        if violated:
            return GaaPResult(
                False, module,
                f"Invariant 違規：{violated}",
                {"violated": violated},
            )

        return GaaPResult(True, module, f"Policy 驗證通過（contract_hash 符合）")


# ---------------------------------------------------------------------------
# GaaPGateway — 統一入口
# ---------------------------------------------------------------------------

class GaaPGateway:
    """
    統一 GaaP 治理閘道：整合七大模組，依序執行所有檢查。
    任一模組失敗則整體拒絕進入 execute 狀態。
    """

    def __init__(
        self,
        token_registry: EphemeralTokenRegistry,
        consent_gate: ConsentGate,
        trust_engine: TrustScoreEngine,
        drift_detector: SemanticDriftDetector,
        rollback_coordinator: RollbackCoordinator,
        resource_guard: ResourceGuard,
        policy_gate: PolicyGate,
    ) -> None:
        self.tokens = EphemeralTokenValidator(token_registry)
        self.consent = consent_gate
        self.trust = trust_engine
        self.drift = drift_detector
        self.rollback = rollback_coordinator
        self.resources = resource_guard
        self.policy = policy_gate

    def authorize_execute(
        self,
        *,
        token_id: str,
        work_contract_id: str,
        requested_capability: str,
        agent_id: str,
        operation_type: str,
        consent_grant_ref: str | None,
        budget_id: str,
        policy_context: dict,
        required_trust_tier: str = "standard",
    ) -> tuple[bool, list[GaaPResult]]:
        """
        執行前授權（對應 GaaP 流程步驟 4–6）。
        回傳 (all_passed, results_list)。
        """
        results = [
            self.policy.check(policy_context),
            self.tokens.validate(token_id, work_contract_id, requested_capability),
            self.trust.check_capability(agent_id, required_trust_tier),
            self.consent.check(operation_type, consent_grant_ref),
            self.resources.check(budget_id),
        ]
        all_passed = all(r.passed for r in results)
        return all_passed, results

    def verify_delivery(
        self,
        *,
        objective: str,
        objective_keywords: list[str],
        deliverable_summary: str,
        metric_thresholds: dict | None = None,
        actual_metrics: dict | None = None,
        forbidden_changes_detected: bool = False,
    ) -> tuple[bool, GaaPResult]:
        """
        交付前驗收（對應 GaaP 流程步驟 9）。
        回傳 (passed, drift_result)。
        """
        result = self.drift.detect(
            objective=objective,
            objective_keywords=objective_keywords,
            deliverable_summary=deliverable_summary,
            metric_thresholds=metric_thresholds,
            actual_metrics=actual_metrics,
            forbidden_changes_detected=forbidden_changes_detected,
        )
        return result.passed, result


def make_contract_hash(contract_content: str) -> str:
    return "sha256:" + hashlib.sha256(contract_content.encode()).hexdigest()[:16]
