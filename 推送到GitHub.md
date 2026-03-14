# 推送到 GitHub 步驟

## 已完成
- ✅ 建立 `.gitignore`
- ✅ 初始化 Git 倉庫
- ✅ 提交所有檔案（55 個檔案，Initial commit）

---

## 接下來請依序操作

### 步驟 1：在 GitHub 建立新倉庫

1. 開啟 [https://github.com/new](https://github.com/new)
2. **Repository name**：輸入名稱（例如 `ai-governance` 或 `ai-chan-hsiu`）
3. **Description**（選填）：例如 `AI 產線治理框架 - 可機讀、可驗證的 AI 工程契約`
4. 選擇 **Public**
5. **不要**勾選 "Add a README file"、"Add .gitignore"、"Choose a license"（專案已有）
6. 點擊 **Create repository**

### 步驟 2：在終端機執行推送指令

建立好倉庫後，GitHub 會顯示倉庫網址，格式為：
```
https://github.com/你的用戶名/倉庫名稱.git
```

在 PowerShell 中執行（**請將網址替換成你的倉庫網址**）：

```powershell
cd "C:\Users\User\Desktop\ai溝通"

# 新增遠端（替換成你的 GitHub 倉庫網址）
git remote add origin https://github.com/你的用戶名/倉庫名稱.git

# 推送到 GitHub（main 或 master，依 GitHub 預設）
git branch -M main
git push -u origin main
```

若 GitHub 顯示預設分支為 `master`，則改用：
```powershell
git push -u origin master
```

### 步驟 3：驗證

推送成功後，到 GitHub 網頁重新整理，應能看到所有檔案已上傳。

---

## 若使用 SSH

若已設定 SSH key，可改用：
```powershell
git remote add origin git@github.com:你的用戶名/倉庫名稱.git
git push -u origin main
```

---

## 常見問題

**Q: 推送時要求登入？**  
A: GitHub 已不再支援密碼，請使用 Personal Access Token（Settings → Developer settings → Personal access tokens）或 SSH key。

**Q: 顯示 "remote origin already exists"？**  
A: 執行 `git remote remove origin` 後再重新 `git remote add origin ...`。
