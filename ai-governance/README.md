# AI Governance（AI 產線治理）

本目錄為 **AI 可機讀、可驗證、可繼承的工程契約**，用於：

- 讓後續 AI 知道前面 AI 做過什麼、為什麼這樣做  
- 防止重寫既有模組（除非符合條件）  
- 防止 scope creep / 複雜度無限膨脹  
- 讓變更具備可追溯、可比較、可回滾、可審核  

---

## 目錄結構

| 檔案 | 層級 | 說明 |
|------|------|------|
| **contract.md** | 1) System Contract | 專案是什麼/不是什麼、不可侵犯原則、Gates |
| **architecture.md** | 2) Architecture + API Canon | 模組邊界、public interfaces、data schema |
| **modules.yaml** | 2) | 模組清單、穩定度、allowed_changes |
| **decisions/** | 3) Decision Ledger | ADR（機讀化決策帳本） |
| **workflow.yaml** | 4) Change Control | 狀態機：Idea → … → Released |
| **change_control.md** | 4) | 變更類型、影響面、驗證、rollback |
| **change_log.jsonl** | 4) | 每筆變更一行 JSON，不可刪改歷史 |
| **budgets.yaml** | Gates | 複雜度預算、單次變更上限 |
| **schemas/** | 硬點 1 | JSON Schema + version-matrix，供 CI 機驗 |
| **interop/** | AI↔AI 互通 | 身份/工單/工件/協作/衝突/安全，見 [interop/README.md](interop/README.md) |

---

## 已落實 vs 已生效

- **已落實**：規則寫在 contract / modules / workflow 裡，人與 AI 讀得到。  
- **已生效**：系統會**拒絕**違規的 commit / PR，不讓其通過。

本專案同時做兩件事：  
- **軟引導**：`.cursor/rules/ai-governance.mdc`（提示工程，非強制；使用者可關、AI 可能偏離、人手可繞過）。  
- **硬治理**：pre-commit + CI + 必要時 PR 自動留言。**沒有通過 = 不能 merge。**

---

## 硬點 1：Machine-checkable schema

- 所有 spec 區塊有對應 **JSON Schema**（`schemas/*.json`），CI 用 `validate_schemas.py` 驗證。  
- **版本允許矩陣**：`schemas/version-matrix.yaml` 定義哪些 `spec:<type> vN` 被接受；v1→v2 升級時在此登記。  
- Markdown 內 spec 維持 fenced block（\`\`\`yaml spec:contract v1 ... \`\`\`），由腳本抽出後驗證。

---

## 硬點 2：Enforcement hooks（拒絕權）

| 層級 | 作法 | 說明 |
|------|------|------|
| **pre-commit** | `.pre-commit-config.yaml` | 本地 `pre-commit run` / commit 時直接擋掉 |
| **CI gate** | `.github/workflows/ai-governance.yml` | PR 不通過不能 merge |
| **repo bot 風格** | 同上 workflow 內步驟 | enforce 失敗時自動在 PR 留言缺失項（change_type、rollback、evidence 等） |

安裝 pre-commit：`pre-commit install`。CI 無需額外設定，push/PR 到 main（或 master）即跑。

---

## 五條 MVP 校驗（CI 強制）

1. **所有變更必須新增一筆 change_log.jsonl**  
2. **touched_files 必須與 git diff 一致**（自動比對）  
3. **觸及 stability: stable 模組**：禁止大改（單檔 diff 行數 ≤ `budgets.yaml` 之 `stable_module_max_diff_lines`，預設 50）  
4. **新增依賴**必須在 `modules.yaml` 之 `dependency_allowlist`，否則 fail  
5. **breaking change** 必須標註且附 `rollback_plan`，否則 fail  

實作於 `ai-governance/scripts/enforce.py`。

---

## AI 執行變更前的強制流程

1. **讀取**：`contract.md` + `modules.yaml` + `workflow.yaml`（以及必要時 `architecture.md`、`budgets.yaml`）。
2. **產出變更提案**：結構化輸出（目標檔案、equivalent_exists、reuse_justification、預算自檢）。
3. **通過 Gates**：Reuse-first → Diff-only → Complexity Budget → Evidence-based（若涉及重寫）。
4. **確認狀態**：僅在 workflow 狀態為 **Approved** 時撰寫 feature 程式碼。
5. **寫入變更**：完成後在 `change_log.jsonl` 追加一筆記錄。

---

## Spec 區塊約定

- 所有 YAML 區塊以 `# spec:<type> v<N>` 標註，AI 僅能依 schema 解讀。  
- 勿刪改既有 spec 的 version 區塊結構，僅能擴充或新增 version。  
- **CI 會用 schema 驗證每個 spec block**；未通過則 build 失敗。
