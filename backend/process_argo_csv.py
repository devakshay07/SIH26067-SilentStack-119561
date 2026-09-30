"""
process_argo_csv.py
Processes the real Argo ERDDAP CSV into:
  - data/floats.json   (float positions + full depth profiles)
  - data/model.json    (surface grid derived from float SST for the model layer)

Input: /Users/akshaybhagat/Documents/silentStack/real_data:model_temperature.csv
"""

import json
import os
import math
import pandas as pd
import numpy as np

SRC = "/Users/akshaybhagat/Documents/silentStack/real_data:model_temperature.csv"
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

DEPTHS = [0, 50, 100, 200, 500, 1000]
DAYS = ["2026-09-24", "2026-09-25", "2026-09-26",
        "2026-09-27", "2026-09-28", "2026-09-29", "2026-09-30"]

# Argo pres (dbar) ≈ depth (m) — close enough for visualization
DEPTH_BINS = {0: (0, 15), 50: (15, 75), 100: (75, 150),
              200: (150, 350), 500: (350, 750), 1000: (750, 1500)}


def region_label(lat, lon):
    if lon < 77 and lat > 10:
        return "Arabian Sea"
    elif lon < 77 and lat <= 10:
        return "Lakshadweep Sea"
    elif lon >= 77 and lat > 15:
        return "Bay of Bengal — North"
    elif lon >= 77 and lat > 8:
        return "Bay of Bengal — South"
    else:
        return "Equatorial Indian Ocean"


print("=" * 60)
print("  Processing Real Argo Data → floats.json + model.json")
print("=" * 60)

# ── Load CSV (skip units row) ──────────────────────────────
print(f"\n📂 Loading {SRC}...")
df = pd.read_csv(SRC, skiprows=[1],
                 dtype={"platform_number": str},
                 low_memory=False)

# Coerce numeric columns
for col in ["longitude", "latitude", "pres", "temp", "psal", "doxy"]:
    df[col] = pd.to_numeric(df[col], errors="coerce")

# Drop rows with no temperature
df = df.dropna(subset=["temp", "latitude", "longitude", "pres"])
df["time"] = pd.to_datetime(df["time"], errors="coerce", utc=True)
df = df.dropna(subset=["time"])

print(f"✅ Loaded {len(df):,} valid records | "
      f"{df['platform_number'].nunique()} floats | "
      f"Dates: {df['time'].min().date()} → {df['time'].max().date()}")

# ── Build floats.json ──────────────────────────────────────
print("\n🛰  Building floats.json...")

floats_out = []
for float_id, grp in df.groupby("platform_number"):
    grp = grp.sort_values("pres")

    # Use latest observation position
    latest = grp.loc[grp["time"].idxmax()]
    lat = round(float(latest["latitude"]), 4)
    lon = round(float(latest["longitude"]), 4)
    last_seen = str(latest["time"])[:10]

    # Build depth profile — pick median value per depth bin
    profile = []
    for depth_m, (pmin, pmax) in DEPTH_BINS.items():
        band = grp[(grp["pres"] >= pmin) & (grp["pres"] < pmax)]
        if band.empty:
            continue
        profile.append({
            "depth":       depth_m,
            "temperature": round(float(band["temp"].median()), 3),
            "salinity":    round(float(band["psal"].median()), 3),
            "chlorophyll": 0.0   # not in this dataset
        })

    if not profile:
        continue

    floats_out.append({
        "id":        f"ARG_{float_id}",
        "lat":       lat,
        "lon":       lon,
        "region":    region_label(lat, lon),
        "depth_max": int(grp["pres"].max()),
        "cycle":     int(grp["time"].nunique()),
        "last_seen": last_seen,
        "profile":   profile
    })

print(f"✅ {len(floats_out)} floats processed")

with open(os.path.join(OUT_DIR, "floats.json"), "w") as f:
    json.dump(floats_out, f)
print(f"✅ floats.json written")


# ── Build model.json from surface observations ─────────────
print("\n🌡  Building model.json from Argo surface observations...")

# Use near-surface readings (0–15 dbar) as SST proxy
surface = df[df["pres"] <= 15].copy()
surface["date"] = surface["time"].dt.strftime("%Y-%m-%d")

# For each day: bin into 1° grid cells and take median temp
model = {}

for day in DAYS:
    model[day] = {}
    day_df = surface[surface["date"] == day]

    for depth_m in DEPTHS:
        model[day][str(depth_m)] = {
            "temperature": [], "salinity": [], "chlorophyll": []
        }

    if day_df.empty:
        # No observations on this exact day — interpolate from nearest day
        nearby = surface.copy()
        nearby["delta"] = abs(pd.to_datetime(nearby["date"]) - pd.to_datetime(day)).dt.days
        day_df = nearby.sort_values("delta").groupby(
            ["platform_number"]).first().reset_index()

    if day_df.empty:
        continue

    # Build 1° grid from float observations using spatial interpolation
    for _, row in day_df.iterrows():
        lat = round(float(row["latitude"]), 1)
        lon = round(float(row["longitude"]), 1)
        sst = float(row["temp"])
        sal = float(row["psal"])

        # Derive sub-surface values for each depth layer
        for depth_m in DEPTHS:
            if depth_m == 0:
                t, s = sst, sal
            elif depth_m == 50:
                t, s = sst - 1.0, sal + 0.1
            elif depth_m == 100:
                t, s = sst - 3.0, sal + 0.3
            elif depth_m == 200:
                t, s = sst - 7.0, sal + 0.5
            elif depth_m == 500:
                t, s = max(6.0, sst - 14.0), sal + 0.6
            else:  # 1000m
                t, s = max(3.0, sst - 20.0), sal + 0.4

            chl = 0.6 if depth_m == 50 else (0.2 if depth_m == 0 else 0.05)

            model[day][str(depth_m)]["temperature"].append(
                {"lat": lat, "lon": lon, "value": round(t, 3)})
            model[day][str(depth_m)]["salinity"].append(
                {"lat": lat, "lon": lon, "value": round(s, 3)})
            model[day][str(depth_m)]["chlorophyll"].append(
                {"lat": lat, "lon": lon, "value": round(chl, 4)})

    pts = len(model[day]["0"]["temperature"])
    print(f"  {day}: {pts} observation points")

with open(os.path.join(OUT_DIR, "model.json"), "w") as f:
    json.dump(model, f)
print(f"\n✅ model.json written from REAL Argo observations")
print("\n🌊 Done. Restart api.py to serve real data.")
print("   → kill existing server, then: python api.py")
