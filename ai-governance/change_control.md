# Change Control（變更控制）

> 任何改動都必須附：變更類型、影響面、相容性、驗證方式。這是「AI 的變更工單流程」，不是作文。

---

## Spec Block: Change Control Schema

```yaml
# spec:change-control v1
change_types:
  - bugfix
  - refactor
  - feature
  - security
  - perf

required_fields:
  - change_type
  - impact_areas    # [API, data, performance, security]
  - breaking_change
  - rollback_plan
  - verification

verification:
  tests: "單元/整合/回歸 — 至少一類必填"
  lint: "專案約定之 linter"
  static_analysis: "可選"
  perf_budget: "若涉及效能，需符合 budgets.yaml 或註明豁免"
```

---

## 單筆變更登錄格式（對應 change_log.jsonl）

| 欄位 | 必填 | 說明 |
|------|------|------|
| schema | ✓ | "v1" |
| change_id | ✓ | 唯一 ID（可與工單/commit 對應） |
| timestamp | ✓ | ISO 8601 |
| commit_id |  | Git commit hash |
| change_type | ✓ | bugfix / refactor / feature / security / perf |
| breaking | ✓ | true / false |
| touched_files | ✓ | 檔案路徑陣列 |
| rationale | ✓ | 為何做此變更 |
| evidence |  | benchmark / test / log 引用 |
| rollback_plan | ✓（若 breaking） | 如何回滾 |
| impact_areas | ✓ | ["API","data","performance","security"] 之子集 |

---

## 驗證責任

- **Tests**：依 change_type 至少覆蓋對應層級（見專案 test 規範）。
- **Lint / format**：必須通過專案既有規則。
- **Perf budget**：見 `budgets.yaml`，超標需註明理由。

---

*每次 AI 產出 patch 後，必須追加一筆記錄至 `change_log.jsonl`。*
