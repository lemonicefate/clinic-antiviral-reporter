# 採中央 FastAPI 服務與 Tauri 客戶端

中央端固定採 Python 3.12、FastAPI 與單一程序管理的 SQLite，Windows 客戶端採 Tauri 2、React 與 TypeScript，並從版本化 OpenAPI 產生 client；領域規則集中於中央端。客戶端使用固定 Windows 帳號下免管理員的 per-user 安裝與簽章更新，而不是 portable EXE；此取捨以單一寫入者、一致命令語意與可回滾更新換取中央主機依賴。
