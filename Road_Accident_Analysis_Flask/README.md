# Road Accident Analysis & Hotspot Detection

A Flask web application built from the supplied Indian roads accident dataset, EDA notebook, hotspot notebook and HTML dashboard.

## Features

- Exploratory analysis: accident severity, causes, monthly trend, hourly distribution, cities, weather and road types.
- Interactive filters: state, city, severity, cause and date range.
- GIS map: accident points and DBSCAN hotspot centres.
- DBSCAN hotspot detection using a 1 km Haversine radius and `min_samples=5`.
- BallTree nearby-accident counts within 1 km.
- Hotspot summary and accident-record tables.
- CSV outputs saved to `outputs/`.

## Project structure

```text
Road_Accident_Analysis_Flask/
├── app.py
├── requirements.txt
├── README.md
├── data/
│   └── IndianRoads_dataset.xlsx
├── templates/
│   └── index.html
├── static/
│   ├── style.css
│   └── dashboard.js
├── outputs/                 # Generated CSV files
├── notebooks/
│   ├── original_eda.ipynb
│   └── original_hotspot.ipynb
└── legacy/
    └── original_dashboard.html
```

## Run on Windows

1. Extract the ZIP file.
2. Open the extracted project folder in VS Code or Command Prompt.
3. Create a virtual environment:

   ```bash
   python -m venv venv
   ```

4. Activate it:

   ```bash
   venv\Scripts\activate
   ```

5. Install the libraries:

   ```bash
   pip install -r requirements.txt
   ```

6. Start the application:

   ```bash
   python app.py
   ```

7. Open this address in your browser:

   **http://127.0.0.1:5000**

## Run on macOS / Linux

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then visit **http://127.0.0.1:5000**.

## How the analysis works

1. `app.py` reads `data/IndianRoads_dataset.xlsx` using a path relative to the project folder. No machine-specific Windows path is required.
2. Text fields are trimmed and standardized; date, hour and numeric fields are parsed.
3. Records with valid latitude/longitude are passed to DBSCAN. Coordinates are converted to radians and the distance metric is Haversine.
4. BallTree counts records within 1 km of each valid accident location.
5. Processed accident records, density results and hotspot summaries are written to `outputs/`.
6. Flask exposes filtered data through JSON endpoints. The browser uses Chart.js and Leaflet to render the dashboard.

## API endpoints

- `/health` — application and data-load status.
- `/api/filters` — available filter values and date bounds.
- `/api/dashboard` — filtered KPI, chart, hotspot and record data.
- `/api/map` — filtered accident points and hotspot centres.

Example:

```text
http://127.0.0.1:5000/api/dashboard?state=Maharashtra&severity=fatal
```

## Notes

- The map displays up to 2,500 sampled accident points for browser performance. Hotspot centres are computed from all records matching the filters.
- The dashboard needs an internet connection to load the Bootstrap, Chart.js and OpenStreetMap/Leaflet assets from their CDNs.
- DBSCAN cluster IDs are algorithm-generated labels and do not represent official administrative zones.
- The original notebooks are included in `notebooks/` and their workbook paths have been updated to use the bundled `data/IndianRoads_dataset.xlsx` file (whether launched from the project root or the notebooks folder).
- The dataset supplied with this project has 20,000 rows and 23 columns. Outputs are recalculated when the Flask app starts.
