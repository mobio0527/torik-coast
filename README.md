# torik-coast

都歷（Torik）海岸的海陸立體地形頁面，並定時取得中央氣象署的開放資料。

網站：https://mobio0527.github.io/torik-coast/

## 內容

- `index.html`：互動式海陸立體地形（Plotly）。
- `scripts/fetch_cwa.py`：向中央氣象署開放資料平臺取資料。目前是探測階段，只記錄各資料集的回應格式與都歷附近的測站樣本。
- `.github/workflows/fetch-cwa.yml`：排程，每小時執行兩次，結果寫入 `data/`。
- `data/status.json`：最近一次執行的狀態。`data/probe/`：各資料集的格式摘要。

## 設定

排程需要一個名為 `CWA_KEY` 的 repository secret，內容是氣象署開放資料平臺的 API 授權碼。授權碼不寫入任何檔案。

## 資料來源

- 地形：GEBCO Compilation Group (2026) GEBCO 2026 Grid (doi:10.5285/4f68d5c7-45eb-f999-e063-7086abc036fa)。不可用於航行或海上安全用途。
- 氣象、潮汐、海象：交通部中央氣象署開放資料平臺。
