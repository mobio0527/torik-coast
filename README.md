# torik-coast

都歷（Torik）海岸的海陸立體地形頁面，並定時取得中央氣象署的開放資料。

網站：https://mobio0527.github.io/torik-coast/

## 內容

- `index.html`：互動式海陸立體地形（Plotly），以及即時潮位、海象、氣象與預報。
- `scripts/fetch_cwa.py`：向中央氣象署開放資料平臺取資料，依與都歷的距離挑選測站與預報點。
- `.github/workflows/fetch-cwa.yml`：排程，每小時執行兩次，結果寫入 `data/`。
- `data/latest.json`：頁面讀取的最新資料。`data/status.json`：最近一次執行的狀態。

## 設定

排程需要一個名為 `CWA_KEY` 的 repository secret，內容是氣象署開放資料平臺的 API 授權碼。授權碼不寫入任何檔案。

## 資料來源

- 地形：GEBCO Compilation Group (2026) GEBCO 2026 Grid (doi:10.5285/4f68d5c7-45eb-f999-e063-7086abc036fa)。不可用於航行或海上安全用途。
- 氣象、潮汐、海象：交通部中央氣象署開放資料平臺（O-B0076-001、O-B0075-001、O-A0003-001、O-A0001-001、F-A0021-001、F-D0047-037）。

## 觀測資料存檔

每次更新會把海象與氣象觀測累積寫入 `data/archive/`，每月一個 CSV 檔（`marine-YYYY-MM.csv`、`weather-YYYY-MM.csv`），同一測站同一時間只留一筆。`data/archive/index.json` 列出現有檔案與起訖時間。存檔自 2026-11-19 起；更早的資料不在其中。
