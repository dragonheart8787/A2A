# Architecture + API Canon（架構與 API 正典）

> **用途**：讓 AI 知道模組邊界、public interfaces、data schema，避免重寫「不可動的公共面」。

---

## Spec Block: Architecture Overview

```yaml
# spec:architecture v1
layers:
  - name: api
    description: "對外公開介面（HTTP/RPC/CLI 等）"
    modules: []   # 對應 modules.yaml 的 name
  - name: core
    description: "核心業務邏輯"
    modules: []
  - name: data
    description: "資料存取、DB、cache"
    modules: []
  - name: infra
    description: "共用工具、logging、config"
    modules: []

module_boundaries:
  # 每個模組僅能依賴同層或下層，不可依賴上層。
  rule: "dependencies_point_down_only"
```

---

## Public Interfaces（函數簽名、輸入輸出、錯誤碼）

請依專案實際情況填寫；以下為範例結構。

```yaml
# spec:api-canon v1
apis:
  - module: data_loader
    functions:
      - signature: "load_prices(symbols, start, end) -> DataFrame"
        inputs:
          symbols: "list[str]"
          start: "date"
          end: "date"
        outputs: "pandas.DataFrame"
        errors:
          - code: "SYMBOL_NOT_FOUND"
          - code: "RATE_LIMIT"
    events: []   # 若有 event schema 可在此列

  # 新增模組時在此追加，並同步更新 modules.yaml
```

---

## Data Schema（DB、JSON、Protobuf、OpenAPI）

若專案有固定 schema，在此以引用或摘要方式列出，避免 AI 擅自改動。

```yaml
# spec:data-schema v1
schemas:
  - name: "[config_or_db_entity]"
    format: json | protobuf | openapi
    path_or_ref: "[路徑或 URL]"
    mutable: false   # 是否允許 AI 擴充欄位（需走 change control）
```

---

*AI 重寫前必須檢查：目標是否為上述 public 介面或 schema；若是，僅允許不破壞相容性的 patch。*
