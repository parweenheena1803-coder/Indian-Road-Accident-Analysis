from pathlib import Path
import json
import logging
import math

import numpy as np
import pandas as pd
from flask import Flask, jsonify, render_template, request
from sklearn.cluster import DBSCAN
from sklearn.neighbors import BallTree

BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "data" / "IndianRoads_dataset.xlsx"
OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

EARTH_RADIUS_KM = 6371.0088
HOTSPOT_RADIUS_KM = 1.0
MIN_SAMPLES = 5

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def clean_column_names(frame):
    frame.columns = [
        str(col).strip().lower().replace(" ", "_")
        for col in frame.columns
    ]
    return frame


def load_and_analyse():
    """Load the supplied Excel file, clean fields and run DBSCAN + BallTree."""
    if not DATA_PATH.exists():
        raise FileNotFoundError(
            f"Dataset not found at {DATA_PATH}. "
            "Place IndianRoads_dataset.xlsx inside the data folder."
        )

    df = pd.read_excel(DATA_PATH)
    df = clean_column_names(df)

    required = {
        "city", "state", "latitude", "longitude", "date",
        "time", "cause", "accident_severity"
    }
    missing = sorted(required.difference(df.columns))
    if missing:
        raise ValueError(f"Dataset is missing required columns: {missing}")

    # Standardize text fields without changing the source workbook.
    text_columns = df.select_dtypes(include=["object"]).columns
    for col in text_columns:
        df[col] = df[col].astype(str).str.strip()
        df[col] = df[col].replace({"": "Unknown", "nan": "Unknown", "None": "Unknown"})

    for col in ["latitude", "longitude", "casualties", "risk_score", "hour"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["accident_severity"] = df["accident_severity"].str.lower()
    df["state"] = df["state"].str.title()
    df["city"] = df["city"].str.title()

    if "hour" not in df.columns or df["hour"].isna().all():
        parsed_time = pd.to_datetime(df["time"], errors="coerce")
        df["hour"] = parsed_time.dt.hour
    df["hour"] = df["hour"].fillna(-1).astype(int)

    if "time_period" not in df.columns:
        df["time_period"] = np.where(
            df["hour"].between(6, 17), "Day", "Night"
        )
    if "day_type" not in df.columns:
        if "is_weekend" in df.columns:
            df["day_type"] = np.where(
                pd.to_numeric(df["is_weekend"], errors="coerce").fillna(0) == 1,
                "Weekend", "Weekday"
            )
        else:
            df["day_type"] = df["date"].dt.dayofweek.map(
                lambda x: "Weekend" if pd.notna(x) and x >= 5 else "Weekday"
            )

    # Keep all records for EDA and tables; only valid coordinates enter clustering.
    valid_geo = (
        df["latitude"].between(-90, 90)
        & df["longitude"].between(-180, 180)
        & df["latitude"].notna()
        & df["longitude"].notna()
    )
    df["cluster_id"] = -1
    df["nearby_accidents"] = np.nan

    geo = df.loc[valid_geo, ["latitude", "longitude"]].copy()
    if not geo.empty:
        coords_rad = np.radians(geo[["latitude", "longitude"]].to_numpy())
        dbscan = DBSCAN(
            eps=HOTSPOT_RADIUS_KM / EARTH_RADIUS_KM,
            min_samples=MIN_SAMPLES,
            metric="haversine",
            algorithm="ball_tree"
        )
        labels = dbscan.fit_predict(coords_rad)
        df.loc[geo.index, "cluster_id"] = labels

        tree = BallTree(coords_rad, metric="haversine")
        nearby = tree.query_radius(
            coords_rad,
            r=HOTSPOT_RADIUS_KM / EARTH_RADIUS_KM,
            count_only=True
        )
        df.loc[geo.index, "nearby_accidents"] = nearby

    df["cluster_id"] = df["cluster_id"].astype(int)

    # Persist outputs for reproducibility and future reuse.
    df.to_csv(OUTPUT_DIR / "accidents_with_clusters.csv", index=False)
    df.loc[valid_geo].sort_values(
        "nearby_accidents", ascending=False
    ).head(5000).to_csv(
        OUTPUT_DIR / "local_density_analysis.csv", index=False
    )

    clustered = df[df["cluster_id"] >= 0].copy()
    if not clustered.empty:
        agg = {
            "accident_count": ("cluster_id", "size"),
            "center_latitude": ("latitude", "mean"),
            "center_longitude": ("longitude", "mean"),
            "fatal_accidents": (
                "accident_severity",
                lambda s: int((s == "fatal").sum())
            ),
            "city": ("city", lambda s: s.mode().iloc[0] if not s.mode().empty else "Unknown"),
            "state": ("state", lambda s: s.mode().iloc[0] if not s.mode().empty else "Unknown"),
        }
        summary = (
            clustered.groupby("cluster_id")
            .agg(**agg)
            .reset_index()
            .sort_values("accident_count", ascending=False)
        )
    else:
        summary = pd.DataFrame(columns=[
            "cluster_id", "accident_count", "center_latitude",
            "center_longitude", "fatal_accidents", "city", "state"
        ])

    summary.to_csv(OUTPUT_DIR / "dbscan_hotspot_summary.csv", index=False)
    logger.info(
        "Loaded %s records; detected %s clusters.",
        len(df), len(summary)
    )
    return df, summary


try:
    DATA, HOTSPOTS = load_and_analyse()
    STARTUP_ERROR = None
except Exception as exc:
    logger.exception("Project data initialization failed")
    DATA = pd.DataFrame()
    HOTSPOTS = pd.DataFrame()
    STARTUP_ERROR = str(exc)


def filtered_data(args):
    df = DATA
    if df.empty:
        return df

    city = args.get("city", "All")
    state = args.get("state", "All")
    severity = args.get("severity", "All")
    cause = args.get("cause", "All")
    start_date = args.get("start_date", "")
    end_date = args.get("end_date", "")

    if city and city != "All":
        df = df[df["city"].astype(str) == city]
    if state and state != "All":
        df = df[df["state"].astype(str) == state]
    if severity and severity != "All":
        df = df[df["accident_severity"].astype(str) == severity.lower()]
    if cause and cause != "All":
        df = df[df["cause"].astype(str) == cause]

    if start_date:
        start = pd.to_datetime(start_date, errors="coerce")
        if pd.notna(start):
            df = df[df["date"] >= start]
    if end_date:
        end = pd.to_datetime(end_date, errors="coerce")
        if pd.notna(end):
            df = df[df["date"] < end + pd.Timedelta(days=1)]
    return df


def safe_records(frame, columns, limit=None):
    available = [c for c in columns if c in frame.columns]
    result = frame[available].copy()
    if limit is not None:
        result = result.head(limit)
    if "date" in result.columns:
        result["date"] = result["date"].dt.strftime("%Y-%m-%d")
    result = result.replace({np.nan: None})
    return result.to_dict(orient="records")


def series_payload(series):
    return {
        "labels": [str(x) for x in series.index.tolist()],
        "values": [int(v) if pd.notna(v) else 0 for v in series.values.tolist()]
    }


@app.route("/")
def index():
    return render_template(
        "index.html",
        startup_error=STARTUP_ERROR
    )


@app.route("/api/filters")
def api_filters():
    if DATA.empty:
        return jsonify({"error": STARTUP_ERROR or "Dataset is not loaded"}), 500
    return jsonify({
        "cities": sorted(DATA["city"].dropna().astype(str).unique().tolist()),
        "states": sorted(DATA["state"].dropna().astype(str).unique().tolist()),
        "severities": sorted(DATA["accident_severity"].dropna().astype(str).unique().tolist()),
        "causes": sorted(DATA["cause"].dropna().astype(str).unique().tolist()),
        "min_date": DATA["date"].min().strftime("%Y-%m-%d"),
        "max_date": DATA["date"].max().strftime("%Y-%m-%d")
    })


@app.route("/api/dashboard")
def api_dashboard():
    df = filtered_data(request.args)
    if df.empty:
        return jsonify({
            "kpis": {"total": 0, "fatal": 0, "cities": 0, "clusters": 0,
                     "casualties": 0, "avg_risk": 0},
            "charts": {}, "hotspots": [], "records": [], "total_records": 0
        })

    fatal = int((df["accident_severity"] == "fatal").sum())
    cluster_count = int(df.loc[df["cluster_id"] >= 0, "cluster_id"].nunique())

    severity = df["accident_severity"].value_counts()
    causes = df["cause"].value_counts().head(10)
    monthly = (
        df.dropna(subset=["date"])
        .assign(month=lambda x: x["date"].dt.to_period("M").astype(str))
        .groupby("month").size().sort_index()
    )
    hourly = df[df["hour"].between(0, 23)]["hour"].value_counts().sort_index()
    top_cities = df["city"].value_counts().head(10)
    weather = df["weather"].value_counts().head(8) if "weather" in df else pd.Series(dtype=int)
    road_types = df["road_type"].value_counts().head(8) if "road_type" in df else pd.Series(dtype=int)

    # Cluster summaries are recalculated for the current filters.
    cl = df[df["cluster_id"] >= 0]
    if not cl.empty:
        hs = (
            cl.groupby("cluster_id")
            .agg(
                accident_count=("cluster_id", "size"),
                fatal_accidents=("accident_severity", lambda s: int((s == "fatal").sum())),
                city=("city", lambda s: s.mode().iloc[0] if not s.mode().empty else "Unknown"),
                state=("state", lambda s: s.mode().iloc[0] if not s.mode().empty else "Unknown"),
                latitude=("latitude", "mean"),
                longitude=("longitude", "mean")
            )
            .reset_index()
            .sort_values("accident_count", ascending=False)
            .head(15)
        )
        hotspots = hs.rename(columns={
            "latitude": "center_latitude",
            "longitude": "center_longitude"
        }).replace({np.nan: None}).to_dict(orient="records")
    else:
        hotspots = []

    records = safe_records(
        df.sort_values("date", ascending=False),
        ["accident_id", "city", "state", "date", "time",
         "accident_severity", "cause", "road_type", "casualties",
         "risk_score", "cluster_id", "nearby_accidents"],
        limit=100
    )

    return jsonify({
        "kpis": {
            "total": int(len(df)),
            "fatal": fatal,
            "cities": int(df["city"].nunique()),
            "clusters": cluster_count,
            "casualties": int(pd.to_numeric(df["casualties"], errors="coerce").fillna(0).sum()),
            "avg_risk": round(float(pd.to_numeric(df["risk_score"], errors="coerce").mean()), 3)
        },
        "charts": {
            "severity": series_payload(severity),
            "causes": series_payload(causes),
            "monthly": series_payload(monthly),
            "hourly": series_payload(hourly),
            "cities": series_payload(top_cities),
            "weather": series_payload(weather),
            "road_types": series_payload(road_types)
        },
        "hotspots": hotspots,
        "records": records,
        "total_records": int(len(df))
    })


@app.route("/api/map")
def api_map():
    df = filtered_data(request.args)
    if df.empty:
        return jsonify({"points": [], "hotspots": []})

    geo = df.dropna(subset=["latitude", "longitude"]).copy()
    if len(geo) > 2500:
        geo = geo.sample(2500, random_state=42)

    points = safe_records(
        geo,
        ["latitude", "longitude", "city", "state",
         "accident_severity", "cause", "cluster_id", "risk_score"]
    )

    cl = df[df["cluster_id"] >= 0]
    if not cl.empty:
        centers = (
            cl.groupby("cluster_id")
            .agg(
                accident_count=("cluster_id", "size"),
                latitude=("latitude", "mean"),
                longitude=("longitude", "mean"),
                city=("city", lambda s: s.mode().iloc[0] if not s.mode().empty else "Unknown"),
                fatal_accidents=("accident_severity", lambda s: int((s == "fatal").sum()))
            )
            .reset_index()
            .sort_values("accident_count", ascending=False)
            .head(100)
        )
        hotspots = centers.replace({np.nan: None}).to_dict(orient="records")
    else:
        hotspots = []

    return jsonify({"points": points, "hotspots": hotspots})


@app.route("/health")
def health():
    return jsonify({
        "status": "ok" if STARTUP_ERROR is None else "error",
        "records_loaded": int(len(DATA)),
        "error": STARTUP_ERROR
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
