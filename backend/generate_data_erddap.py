"""
generate_data_erddap.py
Ingest REAL data from ERDDAP (NOAA) + Argo GDAC — both fully open, no login.

Data sources:
  Model SST:   NOAA CoastWatch ERDDAP (MUR SST Analysis)
  Argo Floats: Ifremer ERDDAP (ArgoFloats dataset)

Run:
    pip install requests pandas numpy
    python generate_data_erddap.py

This overwrites data/model.json and data/floats.json.
Restart the API after running.
"""

import json
import os
import sys
import math
import numpy as np
import pandas as pd
import requests

# ─── Output ───────────────────────────────────────────────
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(OUT_DIR, exist_ok=True)

# ─── Bounding Box ─────────────────────────────────────────
LAT_MIN, LAT_MAX = 0, 25
LON_MIN, LON_MAX = 60, 100

# ─── 7 days ending today ──────────────────────────────────
DAYS = [
    "2026-09-24", "2026-09-25", "2026-09-26",
    "2026-09-27", "2026-09-28", "2026-09-29", "2026-09-30"
]

# Depth levels — SST is surface only; we simulate sub-surface from it
DEPTHS = [0, 50, 100, 200, 500, 1000]


# ─────────────────────────────────────────────────────────
# PART 1 — Ocean Model (NOAA MUR SST via ERDDAP)
# ─────────────────────────────────────────────────────────

def fetch_sst_day(date_str: str) -> pd.DataFrame:
    """Fetch sea surface temperature for one day from NOAA ERDDAP."""
    # MUR SST — 0.01° resolution, but we use stride=8 (~0.08°) for speed
    url = (
        "https://coastwatch.pfeg.noaa.gov/erddap/griddap/jplMURSST41.csv"
        f"?analysed_sst[({date_str}T09:00:00Z):1:({date_str}T09:00:00Z)]"
        f"[({LAT_MIN}.0):8:({LAT_MAX}.0)]"
        f"[({LON_MIN}.0):8:({LON_MAX}.0)]"
    )
    print(f"  Fetching SST for {date_str}...")
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        from io import StringIO
        # ERDDAP CSV has 2 header rows — first is column names, second is units
        df = pd.read_csv(StringIO(resp.text), skiprows=[1])
        df = df.rename(columns={
            "latitude (degrees_north)": "lat",
            "longitude (degrees_east)": "lon",
            "analysed_sst (degree_C)": "sst",
            "latitude": "lat", "longitude": "lon", "analysed_sst": "sst"
        })
        # Keep only lat, lon, sst — drop time and mask columns
        df = df[["lat", "lon", "sst"]].dropna()
        return df
    except Exception as e:
        print(f"  ⚠ Failed to fetch SST for {date_str}: {e}")
        return pd.DataFrame(columns=["lat", "lon", "sst"])


def sst_to_full_profile(sst_val: float, depth: int) -> dict:
    """
    Derive sub-surface temperature, salinity, and chlorophyll from SST.
    Uses standard oceanographic relationships (simplified).
    """
    # Temperature decreases with depth (thermocline ~100-500m)
    if depth == 0:
        temp = sst_val
    elif depth <= 50:
        temp = sst_val - 0.8
    elif depth <= 100:
        temp = sst_val - 2.5
    elif depth <= 200:
        temp = sst_val - 6.0
    elif depth <= 500:
        temp = sst_val - 12.0
    else:  # 1000m
        temp = max(3.5, sst_val - 18.0)

    # Salinity: Arabian Sea saltier than Bay of Bengal
    # We don't have lon here so use a rough global estimate
    salinity = 35.0 + (depth * 0.0008)   # slight increase with depth

    # Chlorophyll: peaks at 50m (deep chlorophyll maximum)
    if depth == 0:
        chl = 0.25
    elif depth == 50:
        chl = 0.70
    elif depth == 100:
        chl = 0.35
    else:
        chl = max(0.01, 0.05 - depth * 0.00005)

    return {
        "temperature": round(float(temp), 3),
        "salinity":    round(float(salinity), 3),
        "chlorophyll": round(float(chl), 4)
    }


def build_model_json():
    """Build model.json from NOAA ERDDAP SST data."""
    print("\n🌡  Fetching ocean model data (NOAA MUR SST)...")
    model = {}

    for day in DAYS:
        df = fetch_sst_day(day)

        if df.empty:
            print(f"  ⚠ No data for {day} — skipping")
            continue

        model[day] = {}
        for depth in DEPTHS:
            model[day][str(depth)] = {
                "temperature": [], "salinity": [], "chlorophyll": []
            }
            for _, row in df.iterrows():
                derived = sst_to_full_profile(row["sst"], depth)
                pt = {"lat": round(float(row["lat"]), 2), "lon": round(float(row["lon"]), 2)}
                for var in ["temperature", "salinity", "chlorophyll"]:
                    model[day][str(depth)][var].append({**pt, "value": derived[var]})

        total = len(df)
        print(f"  ✅ {day}: {total} surface grid points processed across {len(DEPTHS)} depth levels")

    out_path = os.path.join(OUT_DIR, "model.json")
    with open(out_path, "w") as f:
        json.dump(model, f)
    print(f"\n✅ model.json written with REAL NOAA SST data")
    return model


# ─────────────────────────────────────────────────────────
# PART 2 — Argo Floats (Ifremer ERDDAP)
# ─────────────────────────────────────────────────────────

def fetch_argo_floats():
    """Fetch real Argo float profile data from Ifremer ERDDAP."""
    print("\n🛰  Fetching Argo float data (Ifremer ERDDAP)...")

    # Fetch last 30 days of Indian Ocean Argo profiles
    url = (
        "https://www.ifremer.fr/erddap/tabledap/ArgoFloats.csv"
        "?platform_number,longitude,latitude,time,pres,temp,psal,doxy"
        f"&longitude>={LON_MIN}&longitude<={LON_MAX}"
        f"&latitude>={LAT_MIN}&latitude<={LAT_MAX}"
        "&time>=2026-09-01"
        "&temp!=NaN&psal!=NaN"
        '&orderBy("platform_number,pres")'
    )

    try:
        print("  Connecting to Ifremer ERDDAP...")
        resp = requests.get(url, timeout=90)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ⚠ Ifremer ERDDAP failed: {e}")
        print("  ↳ Trying NOAA Argo mirror...")
        url2 = (
            "https://erddap.ioos.us/erddap/tabledap/ArgoFloats.csv"
            "?platform_number,longitude,latitude,time,pressure,temperature,salinity"
            f"&longitude>={LON_MIN}&longitude<={LON_MAX}"
            f"&latitude>={LAT_MIN}&latitude<={LAT_MAX}"
            "&time>=2026-09-01"
            '&orderBy("platform_number,pressure")'
        )
        try:
            resp = requests.get(url2, timeout=90)
            resp.raise_for_status()
        except Exception as e2:
            print(f"  ⚠ NOAA mirror also failed: {e2}")
            print("  ↳ Using locally cached synthetic floats as fallback")
            return None

    from io import StringIO
    # Skip second header row (units)
    df = pd.read_csv(StringIO(resp.text), skiprows=[1])

    # Normalise column names — ERDDAP varies
    df.columns = [c.split(" (")[0].lower().strip() for c in df.columns]
    rename = {
        "platform_number": "float_id",
        "pres": "depth", "pressure": "depth",
        "temp": "temperature",
        "psal": "salinity", "salinity": "salinity",
        "doxy": "oxygen",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    # Crop and clean
    needed = ["float_id", "latitude", "longitude", "time", "depth", "temperature", "salinity"]
    df = df[[c for c in needed if c in df.columns]].dropna(subset=["depth", "temperature"])
    df["depth"] = pd.to_numeric(df["depth"], errors="coerce")
    df["temperature"] = pd.to_numeric(df["temperature"], errors="coerce")
    df["salinity"] = pd.to_numeric(df["salinity"], errors="coerce").fillna(35.0)
    df = df.dropna(subset=["depth", "temperature"])

    print(f"  ✅ Retrieved {len(df)} profile records from {df['float_id'].nunique()} floats")

    # Build float objects
    floats_out = []
    for float_id, group in df.groupby("float_id"):
        group = group.sort_values("depth")
        lat = float(group["latitude"].iloc[0])
        lon = float(group["longitude"].iloc[0])
        last_date = str(group["time"].iloc[-1])[:10]

        profile = []
        for _, row in group.iterrows():
            profile.append({
                "depth":       round(float(row["depth"]), 1),
                "temperature": round(float(row["temperature"]), 3),
                "salinity":    round(float(row["salinity"]), 3),
                "chlorophyll": 0.0   # Argo BGC not always available
            })

        floats_out.append({
            "id":        f"ARG_{str(float_id)}",
            "lat":       round(lat, 4),
            "lon":       round(lon, 4),
            "region":    "Indian Ocean — Argo Observation",
            "depth_max": max(p["depth"] for p in profile),
            "cycle":     len(profile),
            "last_seen": last_date,
            "profile":   profile,
        })

    return floats_out


def build_floats_json():
    floats = fetch_argo_floats()
    if floats is None:
        print("  ↳ Keeping existing floats.json (synthetic)")
        return
    out_path = os.path.join(OUT_DIR, "floats.json")
    with open(out_path, "w") as f:
        json.dump(floats, f)
    print(f"✅ floats.json written with REAL Argo data — {len(floats)} floats")


# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  INCOIS Ocean Viz — Real Data Ingestion")
    print("  Sources: NOAA CoastWatch ERDDAP + Ifremer Argo ERDDAP")
    print("=" * 60)

    build_model_json()
    build_floats_json()

    print("\n🌊 Done. Restart api.py to serve real data.")
    print("   Citation required for Argo data:")
    print('   "These data were collected and made freely available by')
    print('    the International Argo Program (http://www.argo.ucsd.edu)."')
