"""
gaap_runtime.py — GaaP 執行期治理核心函式庫 v2.1.0

完整實作七大模組 + 四個基礎設施層：
  ── 核心治理模組 ──────────────────────────────────────────────────────────
  1. EphemeralTokenRegistry / EphemeralTokenValidator  — 短命限域令牌
  2. ConsentGate                                       — 明確同意閘門
  3. TrustScoreEngine                                  — Agent 信任評分
  4. SemanticDriftDetector                             — 語意漂移偵測
  5. RollbackCoordinator                               — 多代理回滾協調
  6. ResourceGuard                                     — 資源成本治理
  7. PolicyGate                                        — Policy-as-Code 閘門

  ── 基礎設施層 ────────────────────────────────────────────────────────────
  8. GaaPPersistence   — JSONL 持久化（重啟後狀態不遺失）
  9. ObservabilityTracer — trace_id/span_id/decision_log/tool_call_audit
 10. WorkContractManager — 協商綁定（hash 連結，防 scope creep）
 11. ArtifactRegistry    — content hash 登記 + provenance chain

  ── 統一入口 ──────────────────────────────────────────────────────────────
  12. GaaPGateway — 整合七大模組 + 四層基礎設施，單一 API 入口

依賴：Python 3.9+ stdlib only（hashlib, json, uuid, time, dataclasses, pathlib）
執行：python examples/demo_full_flow.py
測試：python -m pytest tests/test_gaap_runtime.py -v
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


# ═══════════════════════════════════════════════════════════════════════════════
# 共用資料結構
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class GaaPResult:
    passed: bool
    module: str
    message: str
    details: dict = field(default_factory=dict)
    trace_id: str | None = None
    span_id:  str | None = None

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.module}: {self.message}"

    def to_dict(self) -> dict:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()

def _sha256(data: str) -> str:
    return "sha256:" + hashlib.sha256(data.encode()).hexdigest()[:16]

def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


# ═══════════════════════════════════════════════════════════════════════════════
# 8. GaaPPersistence — JSONL 持久化層
# ═══════════════════════════════════════════════════════════════════════════════

class GaaPPersistence:
    """
    將 GaaP 執行期狀態持久化至 JSONL 檔案。
    每行一筆記錄，append-only，重啟後可從磁碟重載。
    預設目錄：.gaap_data/（可透過 data_dir 參數指定）
    """

    def __init__(self, data_dir: str | Path = ".gaap_data") -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._files = {
            "tokens":    self.data_dir / "tokens.jsonl",
            "consents":  self.data_dir / "consents.jsonl",
            "reputation":self.data_dir / "reputation.jsonl",
            "audit":     self.data_dir / "audit.jsonl",
            "contracts": self.data_dir / "contracts.jsonl",
            "artifacts": self.data_dir / "artifacts.jsonl",
        }

    # ── 寫入 ──────────────────────────────────────────────────────────────────

    def append(self, store: str, record: dict) -> None:
        path = self._files.get(store)
        if path is None:
            return
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ── 讀取 ──────────────────────────────────────────────────────────────────

    def load_all(self, store: str) -> list[dict]:
        path = self._files.get(store)
        if not path or not path.exists():
            return []
        records = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return records

    def iter_records(self, store: str) -> Iterator[dict]:
        for r in self.load_all(store):
            yield r

    # ── 快照（重新整理去重） ──────────────────────────────────────────────────

    def snapshot_latest(self, store: str, key_field: str) -> dict[str, dict]:
        """回傳每個 key 最後一筆記錄（模擬 key-value store 的 latest state）"""
        result: dict[str, dict] = {}
        for r in self.iter_records(store):
            k = r.get(key_field)
            if k:
                result[k] = r
        return result

    def data_path(self, store: str) -> Path:
        return self._files.get(store, self.data_dir / f"{store}.jsonl")


# ═══════════════════════════════════════════════════════════════════════════════
# 9. ObservabilityTracer — 可觀測性追蹤
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Span:
    trace_id: str
    span_id:  str
    parent_span_id: str | None
    operation: str
    started_at: float
    ended_at: float | None = None
    attributes: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    status: str = "ok"   # ok | error

    def end(self, status: str = "ok") -> None:
        self.ended_at = time.time()
        self.status   = status

    def add_event(self, name: str, attrs: dict | None = None) -> None:
        self.events.append({
            "name":      name,
            "timestamp": _now_iso(),
            "attrs":     attrs or {},
        })

    def duration_ms(self) -> float | None:
        if self.ended_at is None:
            return None
        return (self.ended_at - self.started_at) * 1000

    def to_dict(self) -> dict:
        return {
            "trace_id":       self.trace_id,
            "span_id":        self.span_id,
            "parent_span_id": self.parent_span_id,
            "operation":      self.operation,
            "started_at":     datetime.fromtimestamp(self.started_at, tz=timezone.utc).isoformat(),
            "ended_at":       datetime.fromtimestamp(self.ended_at,   tz=timezone.utc).isoformat() if self.ended_at else None,
            "duration_ms":    self.duration_ms(),
            "attributes":     self.attributes,
            "events":         self.events,
            "status":         self.status,
        }


class ObservabilityTracer:
    """
    W3C TraceContext 相容的 trace/span 追蹤。
    decision_log 與 tool_call_audit 同樣記錄於此，可匯出至 SIEM / OTel。
    """

    def __init__(self, persistence: GaaPPersistence | None = None) -> None:
        self._persistence = persistence
        self._spans:        dict[str, Span] = {}
        self._decision_log: list[dict]      = []
        self._tool_audit:   list[dict]      = []

    # ── Trace / Span ──────────────────────────────────────────────────────────

    def new_trace(self) -> str:
        return _new_id("trace-")

    def start_span(
        self,
        operation: str,
        trace_id:  str,
        parent_span_id: str | None = None,
        attributes: dict | None = None,
    ) -> Span:
        span = Span(
            trace_id       = trace_id,
            span_id        = _new_id("span-"),
            parent_span_id = parent_span_id,
            operation      = operation,
            started_at     = time.time(),
            attributes     = attributes or {},
        )
        self._spans[span.span_id] = span
        return span

    def end_span(self, span: Span, status: str = "ok") -> None:
        span.end(status)
        if self._persistence:
            self._persistence.append("audit", {"_type": "span", **span.to_dict()})

    # ── Decision Log ──────────────────────────────────────────────────────────

    def log_decision(
        self,
        module:       str,
        decision:     str,
        reason:       str,
        result:       bool,
        citation_refs: list[str] | None = None,
        trace_id:     str | None = None,
        span_id:      str | None = None,
    ) -> None:
        entry = {
            "_type":        "decision",
            "timestamp":    _now_iso(),
            "module":       module,
            "decision":     decision,
            "reason":       reason,
            "result":       result,
            "citation_refs":citation_refs or [],
            "trace_id":     trace_id,
            "span_id":      span_id,
        }
        self._decision_log.append(entry)
        if self._persistence:
            self._persistence.append("audit", entry)

    # ── Tool Call Audit ───────────────────────────────────────────────────────

    def audit_tool_call(
        self,
        tool:       str,
        input_data: Any,
        output_ref: str | None = None,
        span_id:    str | None = None,
    ) -> None:
        input_hash = _sha256(json.dumps(input_data, sort_keys=True, default=str))
        entry = {
            "_type":      "tool_call",
            "timestamp":  _now_iso(),
            "tool":       tool,
            "input_hash": input_hash,
            "output_ref": output_ref,
            "span_id":    span_id,
        }
        self._tool_audit.append(entry)
        if self._persistence:
            self._persistence.append("audit", entry)

    # ── 匯出 ──────────────────────────────────────────────────────────────────

    def export_jsonl(self) -> list[dict]:
        """回傳完整稽核日誌（spans + decisions + tool calls）"""
        data: list[dict] = []
        for span in self._spans.values():
            data.append({"_type": "span", **span.to_dict()})
        data.extend(self._decision_log)
        data.extend(self._tool_audit)
        return data

    def get_decision_log(self) -> list[dict]:
        return list(self._decision_log)

    def get_tool_audit(self) -> list[dict]:
        return list(self._tool_audit)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. WorkContractManager — 協商綁定
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class WorkContract:
    work_contract_id:  str
    contract_hash:     str
    parties:           list[str]
    scope_ref:         str
    capability_snapshot: dict
    created_at:        str
    status:            str = "active"   # active | closed | violated

    def to_dict(self) -> dict:
        return asdict(self)


class WorkContractManager:
    """
    實作 negotiation-binds.yaml 的執行期邏輯。
    雙方能力交換 → 產生 WorkContract（hash 綁定）→ 後續訊息驗證。
    """

    def __init__(self, persistence: GaaPPersistence | None = None) -> None:
        self._persistence = persistence
        self._contracts: dict[str, WorkContract] = {}
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if not self._persistence:
            return
        for r in self._persistence.iter_records("contracts"):
            wc = WorkContract(**{k: v for k, v in r.items() if k in WorkContract.__dataclass_fields__})
            self._contracts[wc.work_contract_id] = wc

    # ── 建立 ──────────────────────────────────────────────────────────────────

    def create(
        self,
        owner_capabilities:    dict,
        consumer_capabilities: dict,
        scope_ref:             str,
        parties:               list[str],
    ) -> WorkContract:
        """
        雙方 capability + constraints 快照 → 產生 WorkContract（hash）。
        後續所有 message 必須攜帶 work_contract_id，否則 reject。
        """
        snapshot = {
            "owner":    owner_capabilities,
            "consumer": consumer_capabilities,
            "scope":    scope_ref,
        }
        content   = json.dumps(snapshot, sort_keys=True)
        wc_hash   = _sha256(content)
        wc_id     = _new_id("WC-")

        contract  = WorkContract(
            work_contract_id    = wc_id,
            contract_hash       = wc_hash,
            parties             = parties,
            scope_ref           = scope_ref,
            capability_snapshot = snapshot,
            created_at          = _now_iso(),
        )
        self._contracts[wc_id] = contract
        if self._persistence:
            self._persistence.append("contracts", contract.to_dict())
        return contract

    # ── 驗證 ──────────────────────────────────────────────────────────────────

    def validate(self, work_contract_id: str) -> GaaPResult:
        module = "WorkContract"
        wc = self._contracts.get(work_contract_id)
        if not wc:
            return GaaPResult(False, module, f"WorkContract {work_contract_id!r} 不存在")
        if wc.status == "violated":
            return GaaPResult(False, module, f"WorkContract {work_contract_id!r} 已標記為 violated")
        if wc.status == "closed":
            return GaaPResult(False, module, f"WorkContract {work_contract_id!r} 已關閉")
        return GaaPResult(
            True, module,
            f"WorkContract {work_contract_id!r} 有效（hash={wc.contract_hash}）",
            {"contract_hash": wc.contract_hash, "parties": wc.parties},
        )

    def close(self, work_contract_id: str) -> None:
        if work_contract_id in self._contracts:
            self._contracts[work_contract_id].status = "closed"

    def get(self, work_contract_id: str) -> WorkContract | None:
        return self._contracts.get(work_contract_id)

    def all_contracts(self) -> list[WorkContract]:
        return list(self._contracts.values())


# ═══════════════════════════════════════════════════════════════════════════════
# 11. ArtifactRegistry — 工件登記 + Provenance Chain
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Artifact:
    artifact_id:   str
    content_hash:  str
    version:       str
    location:      str
    schema_type:   str
    trust:         str         # trusted | verified | untrusted
    immutability:  str         # append_only | mutable
    lineage:       list[str]   # 上游 artifact_id 列表
    registered_at: str
    registered_by: str
    metadata:      dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class ArtifactRegistry:
    """
    實作 deterministic-artifacts.yaml + provenance chain。
    每個工件有 content hash、lineage、trust 標記。
    """

    def __init__(self, persistence: GaaPPersistence | None = None) -> None:
        self._persistence = persistence
        self._artifacts: dict[str, Artifact] = {}
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if not self._persistence:
            return
        for r in self._persistence.iter_records("artifacts"):
            a = Artifact(**{k: v for k, v in r.items() if k in Artifact.__dataclass_fields__})
            self._artifacts[a.artifact_id] = a

    # ── 登記 ──────────────────────────────────────────────────────────────────

    def register(
        self,
        artifact_id:  str,
        content:      str,
        location:     str,
        schema_type:  str,
        trust:        str = "verified",
        immutability: str = "append_only",
        lineage:      list[str] | None = None,
        registered_by:str = "system",
        version:      str = "v1",
        metadata:     dict | None = None,
    ) -> Artifact:
        content_hash = _sha256(content)
        artifact = Artifact(
            artifact_id    = artifact_id,
            content_hash   = content_hash,
            version        = version,
            location       = location,
            schema_type    = schema_type,
            trust          = trust,
            immutability   = immutability,
            lineage        = lineage or [],
            registered_at  = _now_iso(),
            registered_by  = registered_by,
            metadata       = metadata or {},
        )
        self._artifacts[artifact_id] = artifact
        if self._persistence:
            self._persistence.append("artifacts", artifact.to_dict())
        return artifact

    # ── 驗證 ──────────────────────────────────────────────────────────────────

    def verify(self, artifact_id: str, expected_hash: str | None = None) -> GaaPResult:
        module = "ArtifactRegistry"
        a = self._artifacts.get(artifact_id)
        if not a:
            return GaaPResult(False, module, f"Artifact {artifact_id!r} 未登記")
        if a.trust == "untrusted":
            return GaaPResult(
                False, module,
                f"Artifact {artifact_id!r} 標記為 untrusted，需人工審核後才可使用",
            )
        if expected_hash and a.content_hash != expected_hash:
            return GaaPResult(
                False, module,
                f"Artifact {artifact_id!r} hash 不符：expected={expected_hash!r}，actual={a.content_hash!r}",
            )
        return GaaPResult(
            True, module,
            f"Artifact {artifact_id!r} 驗證通過（hash={a.content_hash}，trust={a.trust}）",
            {"content_hash": a.content_hash, "lineage": a.lineage, "trust": a.trust},
        )

    def get_provenance_chain(self, artifact_id: str) -> list[dict]:
        """回傳此工件的完整溯源鏈（遞迴查找 lineage）"""
        chain = []
        visited = set()
        queue = [artifact_id]
        while queue:
            aid = queue.pop(0)
            if aid in visited:
                continue
            visited.add(aid)
            a = self._artifacts.get(aid)
            if a:
                chain.append({
                    "artifact_id":  a.artifact_id,
                    "content_hash": a.content_hash,
                    "trust":        a.trust,
                    "registered_at":a.registered_at,
                    "lineage":      a.lineage,
                })
                queue.extend(a.lineage)
        return chain

    def get(self, artifact_id: str) -> Artifact | None:
        return self._artifacts.get(artifact_id)

    def all_artifacts(self) -> list[Artifact]:
        return list(self._artifacts.values())


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Ephemeral Scoped Capability Token
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class CapabilityToken:
    token_id:             str
    agent_id:             str
    work_contract_id:     str
    scoped_capabilities:  list[str]
    issued_at:            float
    expires_at:           float
    revoked:              bool    = False
    revoked_at:           float | None = None
    revoked_reason:       str    = ""
    task_id:              str | None = None
    issuer_agent_id:      str    = "orchestrator"
    rotation_count:       int    = 0
    max_rotations:        int    = 5

    def to_dict(self) -> dict:
        return asdict(self)

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def ttl_seconds(self) -> float:
        return max(0.0, self.expires_at - time.time())


class EphemeralTokenRegistry:
    """Token 發放 / 撤銷 / 輪換 / 持久化"""

    def __init__(self, persistence: GaaPPersistence | None = None) -> None:
        self._persistence = persistence
        self._tokens: dict[str, CapabilityToken] = {}
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if not self._persistence:
            return
        snapshot = self._persistence.snapshot_latest("tokens", "token_id")
        for r in snapshot.values():
            tok = CapabilityToken(**{k: v for k, v in r.items() if k in CapabilityToken.__dataclass_fields__})
            self._tokens[tok.token_id] = tok

    def issue(
        self,
        agent_id:             str,
        work_contract_id:     str,
        scoped_capabilities:  list[str],
        ttl_seconds:          int = 300,
        task_id:              str | None = None,
        issuer_agent_id:      str = "orchestrator",
    ) -> CapabilityToken:
        now   = time.time()
        token = CapabilityToken(
            token_id            = _new_id("tok-"),
            agent_id            = agent_id,
            work_contract_id    = work_contract_id,
            scoped_capabilities = scoped_capabilities,
            issued_at           = now,
            expires_at          = now + max(0, ttl_seconds),
            task_id             = task_id,
            issuer_agent_id     = issuer_agent_id,
        )
        self._tokens[token.token_id] = token
        if self._persistence:
            self._persistence.append("tokens", token.to_dict())
        return token

    def revoke(self, token_id: str, reason: str = "") -> None:
        tok = self._tokens.get(token_id)
        if tok:
            tok.revoked        = True
            tok.revoked_at     = time.time()
            tok.revoked_reason = reason
            if self._persistence:
                self._persistence.append("tokens", tok.to_dict())

    def rotate(
        self,
        token_id:    str,
        ttl_seconds: int = 300,
    ) -> CapabilityToken | None:
        """輪換 token：撤銷舊 token，發放新 token（繼承相同能力與 contract）"""
        old = self._tokens.get(token_id)
        if not old or old.revoked or old.rotation_count >= old.max_rotations:
            return None
        self.revoke(token_id, reason="rotated")
        new_tok = self.issue(
            agent_id            = old.agent_id,
            work_contract_id    = old.work_contract_id,
            scoped_capabilities = old.scoped_capabilities,
            ttl_seconds         = ttl_seconds,
            task_id             = old.task_id,
            issuer_agent_id     = old.issuer_agent_id,
        )
        new_tok.rotation_count = old.rotation_count + 1
        return new_tok

    def get(self, token_id: str) -> CapabilityToken | None:
        return self._tokens.get(token_id)

    def active_tokens_for(self, agent_id: str) -> list[CapabilityToken]:
        return [
            t for t in self._tokens.values()
            if t.agent_id == agent_id and not t.revoked and not t.is_expired()
        ]

    def all_tokens(self) -> list[CapabilityToken]:
        return list(self._tokens.values())


class EphemeralTokenValidator:
    """模組 1：驗證短命限域令牌"""

    def __init__(
        self,
        registry:  EphemeralTokenRegistry,
        tracer:    ObservabilityTracer | None = None,
    ) -> None:
        self.registry = registry
        self.tracer   = tracer

    def validate(
        self,
        token_id:             str,
        work_contract_id:     str,
        requested_capability: str,
        trace_id:             str | None = None,
        span_id:              str | None = None,
    ) -> GaaPResult:
        module = "EphemeralToken"
        token  = self.registry.get(token_id)

        if token is None:
            r = GaaPResult(False, module, f"Token {token_id!r} 不存在")
        elif token.revoked:
            r = GaaPResult(
                False, module,
                f"Token {token_id!r} 已被撤銷（原因: {token.revoked_reason or '未說明'}）",
                {"revoked_at": token.revoked_at},
            )
        elif token.is_expired():
            expired_ago = time.time() - token.expires_at
            r = GaaPResult(
                False, module,
                f"Token 已過期 {expired_ago:.0f} 秒",
                {"expired_at": datetime.fromtimestamp(token.expires_at, tz=timezone.utc).isoformat()},
            )
        elif token.work_contract_id != work_contract_id:
            r = GaaPResult(
                False, module,
                f"Token 綁定的 WorkContract {token.work_contract_id!r} 與請求的 {work_contract_id!r} 不符",
            )
        elif requested_capability not in token.scoped_capabilities:
            r = GaaPResult(
                False, module,
                f"能力 {requested_capability!r} 不在此 Token 的授權範圍 {token.scoped_capabilities}",
            )
        else:
            r = GaaPResult(
                True, module,
                f"Token 有效（剩餘 {token.ttl_seconds():.0f} 秒，能力 {requested_capability!r} 已授權）",
                {"ttl_left_seconds": token.ttl_seconds(), "agent_id": token.agent_id},
            )

        r.trace_id = trace_id
        r.span_id  = span_id
        if self.tracer:
            self.tracer.log_decision(
                module=module, decision="token_validate",
                reason=r.message, result=r.passed,
                citation_refs=[f"token:{token_id}"],
                trace_id=trace_id, span_id=span_id,
            )
        return r


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Consent Gate
# ═══════════════════════════════════════════════════════════════════════════════

SENSITIVE_OPERATIONS = frozenset({
    "read_sensitive_data", "write_sensitive_data", "delete_data",
    "external_api_call", "credential_access", "payment_operation",
    "identity_verification", "cross_agent_data_share",
    "file_system_write", "code_execution",
})


@dataclass
class ConsentRecord:
    consent_id:          str
    operation_type:      str
    sensitive_fields:    list[str]
    status:              str    # pending | granted | denied | expired
    task_id:             str    = ""
    work_contract_id:    str    = ""
    granted_by:          str | None = None
    granted_at:          float | None = None
    denied_at:           float | None = None
    expires_at:          float | None = None
    scope_description:   str    = ""
    audit_trail:         list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def is_expired(self) -> bool:
        return self.expires_at is not None and time.time() > self.expires_at


class ConsentGate:
    """模組 2：明確同意閘門"""

    def __init__(
        self,
        persistence: GaaPPersistence | None = None,
        tracer:      ObservabilityTracer | None = None,
    ) -> None:
        self._persistence = persistence
        self._tracer      = tracer
        self._consents: dict[str, ConsentRecord] = {}
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if not self._persistence:
            return
        snapshot = self._persistence.snapshot_latest("consents", "consent_id")
        for r in snapshot.values():
            cr = ConsentRecord(**{k: v for k, v in r.items() if k in ConsentRecord.__dataclass_fields__})
            self._consents[cr.consent_id] = cr

    def _save(self, cr: ConsentRecord) -> None:
        if self._persistence:
            self._persistence.append("consents", cr.to_dict())

    def _add_audit_event(self, cr: ConsentRecord, event: str, actor: str = "", note: str = "") -> None:
        cr.audit_trail.append({
            "event":     event,
            "timestamp": _now_iso(),
            "actor":     actor,
            "note":      note,
        })

    def request_consent(
        self,
        operation_type:    str,
        sensitive_fields:  list[str],
        task_id:           str = "",
        work_contract_id:  str = "",
        scope_description: str = "",
        ttl_seconds:       int = 3600,
    ) -> ConsentRecord:
        cr = ConsentRecord(
            consent_id         = _new_id("consent-"),
            operation_type     = operation_type,
            sensitive_fields   = sensitive_fields,
            status             = "pending",
            task_id            = task_id,
            work_contract_id   = work_contract_id,
            scope_description  = scope_description,
            expires_at         = time.time() + ttl_seconds if ttl_seconds > 0 else None,
        )
        self._add_audit_event(cr, "requested")
        self._consents[cr.consent_id] = cr
        self._save(cr)
        return cr

    def grant(self, consent_id: str, granted_by: str = "human", note: str = "") -> bool:
        cr = self._consents.get(consent_id)
        if not cr:
            return False
        if cr.is_expired():
            return False  # 不允許 grant 已過期的 consent
        cr.status     = "granted"
        cr.granted_by = granted_by
        cr.granted_at = time.time()
        self._add_audit_event(cr, "granted", actor=granted_by, note=note)
        self._save(cr)
        return True

    def deny(self, consent_id: str, actor: str = "human", reason: str = "") -> bool:
        cr = self._consents.get(consent_id)
        if not cr:
            return False
        cr.status   = "denied"
        cr.denied_at = time.time()
        self._add_audit_event(cr, "denied", actor=actor, note=reason)
        self._save(cr)
        return True

    def check(
        self,
        operation_type:    str,
        consent_grant_ref: str | None,
        trace_id:          str | None = None,
        span_id:           str | None = None,
    ) -> GaaPResult:
        module = "ConsentGate"

        if operation_type not in SENSITIVE_OPERATIONS:
            r = GaaPResult(True, module, f"操作 {operation_type!r} 不屬於敏感操作，不需要同意")
        elif not consent_grant_ref:
            r = GaaPResult(
                False, module,
                f"敏感操作 {operation_type!r} 缺少 consent_grant_ref；必須先取得同意",
                {"required_from": "human", "operation": operation_type},
            )
        else:
            cr = self._consents.get(consent_grant_ref)
            if cr is None:
                r = GaaPResult(False, module, f"consent_grant_ref {consent_grant_ref!r} 不存在")
            elif cr.is_expired():
                r = GaaPResult(False, module, f"同意已過期（consent_id={consent_grant_ref}）")
            elif cr.status == "denied":
                r = GaaPResult(False, module, f"同意已被拒絕（consent_id={consent_grant_ref}）")
            elif cr.status != "granted":
                r = GaaPResult(False, module, f"同意尚未授予（狀態={cr.status}）")
            else:
                r = GaaPResult(
                    True, module,
                    f"同意已授予（由 {cr.granted_by!r}，操作 {operation_type!r}）",
                    {"consent_id": consent_grant_ref, "granted_by": cr.granted_by},
                )

        r.trace_id = trace_id
        r.span_id  = span_id
        if self._tracer:
            self._tracer.log_decision(
                module=module, decision="consent_check",
                reason=r.message, result=r.passed,
                trace_id=trace_id, span_id=span_id,
            )
        return r

    def get(self, consent_id: str) -> ConsentRecord | None:
        return self._consents.get(consent_id)

    def all_consents(self) -> list[ConsentRecord]:
        return list(self._consents.values())


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Trust Score Engine
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class AgentScore:
    agent_id:           str
    trust_score:        float = 0.7
    tasks_completed:    int   = 0
    tasks_failed:       int   = 0
    policy_violations:  int   = 0
    drift_incidents:    int   = 0
    consent_violations: int   = 0
    rollback_triggered: int   = 0
    last_updated:       str   = field(default_factory=_now_iso)
    score_history:      list[dict] = field(default_factory=list)

    def tier(self) -> str:
        if self.trust_score >= 0.8:
            return "full"
        elif self.trust_score >= 0.6:
            return "standard"
        elif self.trust_score >= 0.4:
            return "restricted"
        return "sandbox_only"

    def to_dict(self) -> dict:
        return asdict(self)


class TrustScoreEngine:
    """模組 3：動態信任評分"""

    DELTAS: dict[str, float] = {
        "task_completed":    +0.02,
        "task_failed":       -0.05,
        "policy_violation":  -0.15,
        "drift_incident":    -0.08,
        "consent_violation": -0.20,
        "rollback_triggered":-0.10,
    }
    MAX_GAIN_PER_TASK = 0.05
    FLOOR   = 0.0
    CEILING = 1.0

    def __init__(
        self,
        persistence: GaaPPersistence | None = None,
        tracer:      ObservabilityTracer | None = None,
    ) -> None:
        self._persistence = persistence
        self._tracer      = tracer
        self._agents: dict[str, AgentScore] = {}
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if not self._persistence:
            return
        snapshot = self._persistence.snapshot_latest("reputation", "agent_id")
        for r in snapshot.values():
            # score_history is embedded; handle gracefully
            a = AgentScore(**{k: v for k, v in r.items() if k in AgentScore.__dataclass_fields__})
            self._agents[a.agent_id] = a

    def get_or_create(self, agent_id: str) -> AgentScore:
        if agent_id not in self._agents:
            self._agents[agent_id] = AgentScore(agent_id=agent_id)
        return self._agents[agent_id]

    def record_event(self, agent_id: str, event: str, task_id: str = "") -> float:
        score = self.get_or_create(agent_id)
        delta = self.DELTAS.get(event, 0.0)
        if event == "task_completed":
            delta = min(delta, self.MAX_GAIN_PER_TASK)
        old_score = score.trust_score
        score.trust_score = round(
            max(self.FLOOR, min(self.CEILING, score.trust_score + delta)), 4
        )
        score.last_updated = _now_iso()
        if hasattr(score, event):
            setattr(score, event, getattr(score, event) + 1)
        score.score_history.append({
            "timestamp": _now_iso(),
            "score":     score.trust_score,
            "delta":     round(delta, 4),
            "reason":    event,
            "task_id":   task_id,
        })
        if self._persistence:
            self._persistence.append("reputation", score.to_dict())
        if self._tracer:
            self._tracer.log_decision(
                module="TrustScore", decision="score_update",
                reason=f"{event}: {old_score:.3f} → {score.trust_score:.3f}",
                result=True,
            )
        return score.trust_score

    def check_capability(
        self,
        agent_id:       str,
        required_tier:  str = "standard",
        trace_id:       str | None = None,
        span_id:        str | None = None,
    ) -> GaaPResult:
        module      = "TrustScore"
        score       = self.get_or_create(agent_id)
        tier_order  = ["sandbox_only", "restricted", "standard", "full"]
        agent_tier  = score.tier()

        if tier_order.index(agent_tier) < tier_order.index(required_tier):
            r = GaaPResult(
                False, module,
                f"Agent {agent_id!r} 信任分數 {score.trust_score:.2f}（{agent_tier} tier），低於要求 {required_tier} tier",
                {"trust_score": score.trust_score, "tier": agent_tier},
            )
        else:
            r = GaaPResult(
                True, module,
                f"Agent {agent_id!r} 信任分數 {score.trust_score:.2f}（{agent_tier} tier），通過",
                {"trust_score": score.trust_score, "tier": agent_tier},
            )

        r.trace_id = trace_id
        r.span_id  = span_id
        if self._tracer:
            self._tracer.log_decision(
                module=module, decision="trust_check",
                reason=r.message, result=r.passed,
                trace_id=trace_id, span_id=span_id,
            )
        return r

    def decay_all(self, rate_per_day: float = 0.001, floor: float = 0.1) -> dict[str, float]:
        """每日衰減（排程呼叫）"""
        results = {}
        for agent_id, score in self._agents.items():
            new_score = max(floor, score.trust_score - rate_per_day)
            if new_score != score.trust_score:
                score.trust_score  = round(new_score, 4)
                score.last_updated = _now_iso()
                if self._persistence:
                    self._persistence.append("reputation", score.to_dict())
            results[agent_id] = score.trust_score
        return results


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Semantic Drift Detector
# ═══════════════════════════════════════════════════════════════════════════════

class SemanticDriftDetector:
    """模組 4：語意漂移偵測"""

    AUTO_REJECT_THRESHOLD = 0.40
    FLAG_THRESHOLD        = 0.15

    def __init__(self, tracer: ObservabilityTracer | None = None) -> None:
        self._tracer = tracer

    def detect(
        self,
        objective:                 str,
        objective_keywords:        list[str],
        deliverable_summary:       str,
        metric_thresholds:         dict[str, float] | None = None,
        actual_metrics:            dict[str, float] | None = None,
        forbidden_changes_detected:bool = False,
        trace_id:                  str | None = None,
        span_id:                   str | None = None,
    ) -> GaaPResult:
        module = "SemanticDrift"

        # 關鍵詞覆蓋率（40%）
        dl = deliverable_summary.lower()
        covered = [kw for kw in objective_keywords if kw.lower() in dl]
        missing  = [kw for kw in objective_keywords if kw.lower() not in dl]
        cov_ratio = len(covered) / len(objective_keywords) if objective_keywords else 1.0

        # 指標達標率（40%）
        metric_pass_ratio = 1.0
        failed_metrics: list[str] = []
        if metric_thresholds and actual_metrics:
            checks = []
            for key, threshold in metric_thresholds.items():
                actual  = actual_metrics.get(key, 0.0)
                passed  = actual >= threshold
                checks.append(passed)
                if not passed:
                    failed_metrics.append(f"{key}: actual={actual} < threshold={threshold}")
            metric_pass_ratio = sum(checks) / len(checks) if checks else 1.0

        # 禁止變更（20%）
        forbidden_score = 0.0 if not forbidden_changes_detected else 1.0

        drift_score = round(
            max(0.0, min(1.0, 1.0 - (cov_ratio * 0.4 + metric_pass_ratio * 0.4 + (1.0 - forbidden_score) * 0.2))),
            3,
        )

        details = {
            "drift_score":         drift_score,
            "keyword_coverage":    f"{len(covered)}/{len(objective_keywords)}",
            "missing_keywords":    missing,
            "failed_metrics":      failed_metrics,
            "forbidden_changes":   forbidden_changes_detected,
        }

        if drift_score > self.AUTO_REJECT_THRESHOLD:
            r = GaaPResult(
                False, module,
                f"語意漂移過高（drift_score={drift_score:.3f} > {self.AUTO_REJECT_THRESHOLD}），自動拒絕",
                {**details, "status": "auto_rejected"},
            )
        elif drift_score > self.FLAG_THRESHOLD:
            r = GaaPResult(
                True, module,
                f"語意漂移警告（drift_score={drift_score:.3f}），建議人工審核",
                {**details, "status": "flag"},
            )
        else:
            r = GaaPResult(
                True, module,
                f"語意對齊良好（drift_score={drift_score:.3f}），通過",
                {**details, "status": "pass"},
            )

        r.trace_id = trace_id
        r.span_id  = span_id
        if self._tracer:
            self._tracer.log_decision(
                module=module, decision="drift_detect",
                reason=r.message, result=r.passed,
                citation_refs=[f"drift_score:{drift_score}"],
                trace_id=trace_id, span_id=span_id,
            )
        return r


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Rollback Coordinator
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RollbackPlan:
    rollback_id:      str
    work_contract_id: str
    trigger:          str
    strategy:         str
    participants:     list[dict]
    status:           str = "planned"
    orchestrator:     str = "system"
    created_at:       str = field(default_factory=_now_iso)
    completed_at:     str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class RollbackCoordinator:
    """模組 5：多代理回滾協調"""

    def __init__(self, tracer: ObservabilityTracer | None = None) -> None:
        self._tracer    = tracer
        self._snapshots: dict[str, str]          = {}
        self._plans:     dict[str, RollbackPlan] = {}

    def register_snapshot(self, agent_id: str, snapshot_ref: str) -> None:
        self._snapshots[agent_id] = snapshot_ref
        if self._tracer:
            self._tracer.audit_tool_call(
                "register_snapshot",
                {"agent_id": agent_id, "snapshot_ref": snapshot_ref},
            )

    def initiate(
        self,
        work_contract_id: str,
        trigger:          str,
        affected_agents:  list[str],
        strategy:         str = "partial_rollback",
        orchestrator:     str = "system",
    ) -> RollbackPlan:
        participants = [
            {
                "agent_id":       a,
                "rollback_action":"restore_snapshot" if a in self._snapshots else "notify_only",
                "snapshot_ref":   self._snapshots.get(a, "NO_SNAPSHOT"),
                "status":         "pending",
            }
            for a in affected_agents
        ]
        plan = RollbackPlan(
            rollback_id      = _new_id("rb-"),
            work_contract_id = work_contract_id,
            trigger          = trigger,
            strategy         = strategy,
            participants     = participants,
            orchestrator     = orchestrator,
        )
        self._plans[plan.rollback_id] = plan
        if self._tracer:
            self._tracer.log_decision(
                module="RollbackCoord", decision="rollback_initiated",
                reason=f"trigger={trigger}, strategy={strategy}, agents={affected_agents}",
                result=True,
            )
        return plan

    def execute(self, rollback_id: str) -> GaaPResult:
        module = "RollbackCoord"
        plan   = self._plans.get(rollback_id)
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
        plan.status       = "completed" if not failed else "partially_completed"
        plan.completed_at = _now_iso()

        return GaaPResult(
            not bool(failed), module,
            f"回滾 {rollback_id}（{plan.strategy}）{'完成' if not failed else '部分完成'}",
            {"participants": results, "status": plan.status},
        )

    def get_plan(self, rollback_id: str) -> RollbackPlan | None:
        return self._plans.get(rollback_id)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Resource Guard
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ResourceBudget:
    budget_id:             str
    task_id:               str
    token_cost_ceiling:    float
    compute_budget_seconds:int
    tool_calls_max:        int
    overflow_action:       str   = "terminate"
    token_cost_actual:     float = 0.0
    compute_seconds_used:  int   = 0
    tool_calls_used:       int   = 0
    output_tokens_max:     int   = 8192
    output_tokens_used:    int   = 0
    network_requests_max:  int   = 10
    network_requests_used: int   = 0
    overflow_events:       list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class ResourceGuard:
    """模組 6：資源成本治理"""

    def __init__(self, tracer: ObservabilityTracer | None = None) -> None:
        self._tracer  = tracer
        self._budgets: dict[str, ResourceBudget] = {}

    def create_budget(
        self,
        task_id:               str,
        token_cost_ceiling:    float = 2.0,
        compute_budget_seconds:int   = 300,
        tool_calls_max:        int   = 50,
        output_tokens_max:     int   = 8192,
        network_requests_max:  int   = 10,
        overflow_action:       str   = "terminate",
    ) -> ResourceBudget:
        b = ResourceBudget(
            budget_id              = _new_id("budget-"),
            task_id                = task_id,
            token_cost_ceiling     = token_cost_ceiling,
            compute_budget_seconds = compute_budget_seconds,
            tool_calls_max         = tool_calls_max,
            output_tokens_max      = output_tokens_max,
            network_requests_max   = network_requests_max,
            overflow_action        = overflow_action,
        )
        self._budgets[b.budget_id] = b
        return b

    def record_usage(
        self,
        budget_id:        str,
        token_cost:       float = 0.0,
        compute_seconds:  int   = 0,
        tool_calls:       int   = 0,
        output_tokens:    int   = 0,
        network_requests: int   = 0,
    ) -> None:
        b = self._budgets.get(budget_id)
        if not b:
            return
        b.token_cost_actual    += token_cost
        b.compute_seconds_used += compute_seconds
        b.tool_calls_used      += tool_calls
        b.output_tokens_used   += output_tokens
        b.network_requests_used += network_requests
        if self._tracer:
            self._tracer.audit_tool_call(
                "record_usage",
                {"budget_id": budget_id, "token_cost": token_cost,
                 "compute_seconds": compute_seconds, "tool_calls": tool_calls},
            )

    def check(
        self,
        budget_id: str,
        trace_id:  str | None = None,
        span_id:   str | None = None,
    ) -> GaaPResult:
        module = "ResourceGuard"
        b = self._budgets.get(budget_id)
        if not b:
            return GaaPResult(False, module, f"Budget {budget_id!r} 不存在")

        checks = [
            ("token_cost_ceiling",     b.token_cost_actual,    b.token_cost_ceiling,    "token_cost"),
            ("compute_budget_seconds", b.compute_seconds_used, b.compute_budget_seconds,"compute_seconds"),
            ("tool_calls_max",         b.tool_calls_used,      b.tool_calls_max,        "tool_calls"),
            ("output_tokens_max",      b.output_tokens_used,   b.output_tokens_max,     "output_tokens"),
            ("network_requests_max",   b.network_requests_used,b.network_requests_max,  "network_requests"),
        ]
        violations = []
        for label, actual, limit, unit in checks:
            if actual > limit:
                violations.append(f"{unit}: {actual} > limit {limit}")
                b.overflow_events.append({
                    "resource": unit, "limit": limit, "actual": actual,
                    "timestamp": _now_iso(), "action_taken": b.overflow_action,
                })

        if violations:
            r = GaaPResult(
                False, module,
                f"資源超限（overflow_action={b.overflow_action}）：{'; '.join(violations)}",
                {"violations": violations, "overflow_action": b.overflow_action,
                 "actual": {"token_cost": b.token_cost_actual,
                            "compute_seconds": b.compute_seconds_used,
                            "tool_calls": b.tool_calls_used}},
            )
        else:
            r = GaaPResult(
                True, module,
                f"資源用量正常（token={b.token_cost_actual:.3f}/{b.token_cost_ceiling}，"
                f"compute={b.compute_seconds_used}s/{b.compute_budget_seconds}s，"
                f"tool_calls={b.tool_calls_used}/{b.tool_calls_max}）",
            )

        r.trace_id = trace_id
        r.span_id  = span_id
        if self._tracer:
            self._tracer.log_decision(
                module=module, decision="resource_check",
                reason=r.message, result=r.passed,
                trace_id=trace_id, span_id=span_id,
            )
        return r

    def get(self, budget_id: str) -> ResourceBudget | None:
        return self._budgets.get(budget_id)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Policy Gate
# ═══════════════════════════════════════════════════════════════════════════════

class PolicyGate:
    """模組 7：Policy-as-Code 閘門"""

    def __init__(
        self,
        contract_hash: str,
        invariants:    list[str] | None = None,
        tracer:        ObservabilityTracer | None = None,
    ) -> None:
        self.contract_hash = contract_hash
        self.invariants    = invariants or ["INV-API-001", "INV-MOD-002", "INV-DEP-003", "INV-BREAK-004", "INV-SCHEMA-005", "INV-DRIFT-006"]
        self._tracer       = tracer

    def check(
        self,
        policy_context: dict,
        trace_id:       str | None = None,
        span_id:        str | None = None,
    ) -> GaaPResult:
        module = "PolicyGate"
        incoming_hash = policy_context.get("contract_hash", "")

        if incoming_hash != self.contract_hash:
            r = GaaPResult(
                False, module,
                f"Policy context 的 contract_hash 不符：expected={self.contract_hash!r}，got={incoming_hash!r}",
                {"expected": self.contract_hash, "received": incoming_hash},
            )
        else:
            violated = [
                inv for inv in policy_context.get("violated_invariants", [])
                if inv in self.invariants
            ]
            if violated:
                r = GaaPResult(False, module, f"Invariant 違規：{violated}", {"violated": violated})
            else:
                r = GaaPResult(True, module, f"Policy 驗證通過（contract_hash 符合）")

        r.trace_id = trace_id
        r.span_id  = span_id
        if self._tracer:
            self._tracer.log_decision(
                module=module, decision="policy_check",
                reason=r.message, result=r.passed,
                citation_refs=[f"contract:{self.contract_hash}"],
                trace_id=trace_id, span_id=span_id,
            )
        return r


# ═══════════════════════════════════════════════════════════════════════════════
# 12. GaaPGateway — 統一入口
# ═══════════════════════════════════════════════════════════════════════════════

class GaaPGateway:
    """
    統一 GaaP 治理閘道：整合七大模組 + 四層基礎設施。
    authorize_execute()  — 執行前授權（五層並發）
    verify_delivery()    — 交付前語意漂移偵測
    new_trace()          — 建立新 trace_id，用於跨請求關聯
    """

    def __init__(
        self,
        token_registry:      EphemeralTokenRegistry,
        consent_gate:        ConsentGate,
        trust_engine:        TrustScoreEngine,
        drift_detector:      SemanticDriftDetector,
        rollback_coordinator:RollbackCoordinator,
        resource_guard:      ResourceGuard,
        policy_gate:         PolicyGate,
        tracer:              ObservabilityTracer | None = None,
        work_contract_mgr:   WorkContractManager  | None = None,
        artifact_registry:   ArtifactRegistry     | None = None,
    ) -> None:
        self._token_validator = EphemeralTokenValidator(token_registry, tracer)
        self.tokens        = token_registry
        self.consent       = consent_gate
        self.trust         = trust_engine
        self.drift         = drift_detector
        self.rollback      = rollback_coordinator
        self.resources     = resource_guard
        self.policy        = policy_gate
        self.tracer        = tracer
        self.contracts     = work_contract_mgr
        self.artifacts     = artifact_registry

    def new_trace(self) -> str:
        return self.tracer.new_trace() if self.tracer else _new_id("trace-")

    def authorize_execute(
        self,
        *,
        token_id:             str,
        work_contract_id:     str,
        requested_capability: str,
        agent_id:             str,
        operation_type:       str,
        consent_grant_ref:    str | None,
        budget_id:            str,
        policy_context:       dict,
        required_trust_tier:  str = "standard",
        trace_id:             str | None = None,
    ) -> tuple[bool, list[GaaPResult]]:
        """
        執行前授權（五層依序並發）：
          Policy Gate → Token Validate → Trust Score → Consent Gate → Resource Guard
        同時驗證 WorkContract（若已配置）。
        回傳 (all_passed, results_list)。
        """
        if not trace_id and self.tracer:
            trace_id = self.tracer.new_trace()

        span = self.tracer.start_span(
            "authorize_execute", trace_id or "", attributes={"agent_id": agent_id}
        ) if self.tracer else None

        results: list[GaaPResult] = []

        # WorkContract 驗證（若有配置）
        if self.contracts:
            wc_result = self.contracts.validate(work_contract_id)
            wc_result.trace_id = trace_id
            if span:
                wc_result.span_id = span.span_id
            results.append(wc_result)
            if not wc_result.passed:
                if span:
                    self.tracer.end_span(span, "error")  # type: ignore[union-attr]
                return False, results

        # 五層主要檢查
        sid = span.span_id if span else None
        checks = [
            self.policy.check(policy_context, trace_id, sid),
            self._token_validator.validate(token_id, work_contract_id, requested_capability, trace_id, sid),
            self.trust.check_capability(agent_id, required_trust_tier, trace_id, sid),
            self.consent.check(operation_type, consent_grant_ref, trace_id, sid),
            self.resources.check(budget_id, trace_id, sid),
        ]
        results.extend(checks)
        all_passed = all(r.passed for r in results)

        if span:
            self.tracer.end_span(span, "ok" if all_passed else "error")  # type: ignore[union-attr]

        return all_passed, results

    def verify_delivery(
        self,
        *,
        objective:                 str,
        objective_keywords:        list[str],
        deliverable_summary:       str,
        metric_thresholds:         dict | None = None,
        actual_metrics:            dict | None = None,
        forbidden_changes_detected:bool        = False,
        trace_id:                  str | None  = None,
    ) -> tuple[bool, GaaPResult]:
        span = self.tracer.start_span("verify_delivery", trace_id or "") if self.tracer else None
        sid  = span.span_id if span else None

        result = self.drift.detect(
            objective                  = objective,
            objective_keywords         = objective_keywords,
            deliverable_summary        = deliverable_summary,
            metric_thresholds          = metric_thresholds,
            actual_metrics             = actual_metrics,
            forbidden_changes_detected = forbidden_changes_detected,
            trace_id                   = trace_id,
            span_id                    = sid,
        )
        if span:
            self.tracer.end_span(span, "ok" if result.passed else "error")  # type: ignore[union-attr]

        # 若漂移事件觸發，更新 agent 信任分數（需要提供 agent_id 時可選）
        return result.passed, result


# ═══════════════════════════════════════════════════════════════════════════════
# 工廠函數
# ═══════════════════════════════════════════════════════════════════════════════

def make_contract_hash(contract_content: str) -> str:
    return _sha256(contract_content)


def build_gateway(
    contract_content: str = "project:GaaP version:2.1.0",
    data_dir:         str | Path = ".gaap_data",
    persist:          bool = False,
) -> tuple[GaaPGateway, EphemeralTokenRegistry, ConsentGate, TrustScoreEngine, ResourceGuard, RollbackCoordinator]:
    """
    建立完整的 GaaPGateway 實例（含持久化與可觀測性）。

    Args:
        contract_content: 用來產生 contract_hash 的字串
        data_dir:         JSONL 持久化目錄（persist=True 時有效）
        persist:          是否啟用磁碟持久化（True=重啟後狀態保留）

    Returns:
        (gateway, token_registry, consent_gate, trust_engine, resource_guard, rollback_coordinator)
    """
    persistence  = GaaPPersistence(data_dir) if persist else None
    tracer       = ObservabilityTracer(persistence)
    contract_hash= make_contract_hash(contract_content)

    registry  = EphemeralTokenRegistry(persistence)
    consent   = ConsentGate(persistence, tracer)
    trust     = TrustScoreEngine(persistence, tracer)
    drift     = SemanticDriftDetector(tracer)
    rollback  = RollbackCoordinator(tracer)
    resources = ResourceGuard(tracer)
    policy    = PolicyGate(contract_hash, tracer=tracer)
    contracts = WorkContractManager(persistence)
    artifacts = ArtifactRegistry(persistence)

    gateway = GaaPGateway(
        token_registry       = registry,
        consent_gate         = consent,
        trust_engine         = trust,
        drift_detector       = drift,
        rollback_coordinator = rollback,
        resource_guard       = resources,
        policy_gate          = policy,
        tracer               = tracer,
        work_contract_mgr    = contracts,
        artifact_registry    = artifacts,
    )
    return gateway, registry, consent, trust, resources, rollback
