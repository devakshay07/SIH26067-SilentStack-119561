"""
generate_data.py
Synthetic ocean data generator for India's EEZ.
Coverage: Lat 0-25°N, Lon 60-100°E
Variables: Temperature, Salinity, Chlorophyll
Depths: 0, 50, 100, 200, 500, 1000m
Time steps: 7 days
Argo Floats: 25 simulated instruments
"""

import json
import random
import math
import os

random.seed(42)  # Reproducible output

# --- Config ---
LAT_RANGE = (0, 25)
LON_RANGE = (60, 100)
GRID_STEP = 0.8  # degrees — ~2100 grid points, fast to render
DEPTHS = [0, 50, 100, 200, 500, 1000]
DAYS = ["2026-09-24", "2026-09-25", "2026-09-26",
        "2026-09-27", "2026-09-28", "2026-09-29", "2026-09-30"]
NUM_FLOATS = 25


def is_ocean(lat, lon):
    """Rough mask — exclude Indian landmass."""
    # Simple bounding box for the subcontinent
    if 8 < lat < 35 and 68 < lon < 88:
        return False
    if lat > 20 and 68 < lon < 78:
        return False
    return True


def base_temperature(lat, lon, depth):
    """Realistic SST model: warmer near equator, cools with depth."""
    sst = 30.0 - (lat * 0.4) + random.gauss(0, 0.5)
    depth_cooling = depth * 0.018  # ~18°C per 1000m
    lon_effect = math.sin((lon - 60) * 0.05) * 0.8
    return round(max(2.0, sst - depth_cooling + lon_effect), 2)


def base_salinity(lat, lon, depth):
    """Salinity: Arabian Sea saltier, Bay of Bengal fresher at surface."""
    if lon < 80:  # Arabian Sea
        base = 36.5 + random.gauss(0, 0.3)
    else:  # Bay of Bengal
        base = 33.5 + random.gauss(0, 0.4)
    depth_effect = min(depth * 0.001, 1.5)  # slight increase with depth
    return round(base + depth_effect, 3)


def base_chlorophyll(lat, lon, depth):
    """Chlorophyll: peaks at ~50m (deep chlorophyll max), negligible below 200m."""
    if depth == 0:
        val = 0.3 + random.uniform(0, 0.4)
    elif depth == 50:
        val = 0.8 + random.uniform(0, 0.6)   # DCM peak
    elif depth == 100:
        val = 0.4 + random.uniform(0, 0.3)
    else:
        val = max(0.01, 0.05 + random.gauss(0, 0.02))
    # Coastal upwelling near west coast
    if lon < 74:
        val *= 1.8
    return round(val, 4)


def generate_model_field():
    """Generate model grid for all variables, depths, and time steps."""
    model = {}
    lats = [round(LAT_RANGE[0] + i * GRID_STEP, 1)
            for i in range(int((LAT_RANGE[1] - LAT_RANGE[0]) / GRID_STEP) + 1)]
    lons = [round(LON_RANGE[0] + j * GRID_STEP, 1)
            for j in range(int((LON_RANGE[1] - LON_RANGE[0]) / GRID_STEP) + 1)]

    for day_idx, day in enumerate(DAYS):
        model[day] = {}
        for depth in DEPTHS:
            model[day][str(depth)] = {
                "temperature": [],
                "salinity": [],
                "chlorophyll": []
            }
            # Time drift: slight warming trend
            time_drift = day_idx * 0.08

            for lat in lats:
                for lon in lons:
                    if not is_ocean(lat, lon):
                        continue
                    t = base_temperature(lat, lon, depth) + time_drift
                    s = base_salinity(lat, lon, depth)
                    c = base_chlorophyll(lat, lon, depth)
                    point = {"lat": lat, "lon": lon}
                    model[day][str(depth)]["temperature"].append(
                        {**point, "value": round(t, 2)})
                    model[day][str(depth)]["salinity"].append(
                        {**point, "value": round(s, 3)})
                    model[day][str(depth)]["chlorophyll"].append(
                        {**point, "value": round(c, 4)})

    return model


def generate_argo_floats():
    """Generate 25 Argo float positions with realistic profiles."""
    floats = []

    # Known oceanographic regions
    regions = [
        (8.5, 76.2, "Arabian Sea — Upwelling Zone"),
        (15.0, 65.0, "Central Arabian Sea"),
        (12.3, 80.4, "Bay of Bengal — North"),
        (5.2, 85.6, "Equatorial Indian Ocean"),
        (20.1, 90.3, "Bay of Bengal — South"),
        (10.0, 72.5, "Lakshadweep Sea"),
        (18.5, 70.1, "Arabian Sea — Deep"),
        (6.8, 79.3, "Sri Lanka Dome"),
    ]

    for i in range(NUM_FLOATS):
        region = regions[i % len(regions)]
        lat = round(region[0] + random.uniform(-1.5, 1.5), 4)
        lon = round(region[1] + random.uniform(-1.5, 1.5), 4)
        float_id = f"ARG_{6900000 + i:07d}"
        profile_depths = [0, 25, 50, 75, 100, 150, 200,
                          300, 500, 750, 1000, 1500, 2000]

        profile = []
        for d in profile_depths:
            t = base_temperature(lat, lon, d)
            s = base_salinity(lat, lon, d)
            c = base_chlorophyll(lat, lon, d) if d <= 200 else 0.01
            profile.append({
                "depth": d,
                "temperature": t,
                "salinity": s,
                "chlorophyll": round(c, 4)
            })

        floats.append({
            "id": float_id,
            "lat": lat,
            "lon": lon,
            "region": region[2],
            "depth_max": 2000,
            "cycle": random.randint(50, 380),
            "last_seen": DAYS[-1],
            "profile": profile
        })

    return floats


if __name__ == "__main__":
    out_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(out_dir, exist_ok=True)

    print("⏳ Generating ocean model field data...")
    model = generate_model_field()
    with open(os.path.join(out_dir, "model.json"), "w") as f:
        json.dump(model, f)
    print(f"✅ model.json written — {sum(len(model[d][str(depth)]['temperature']) for d in DAYS for depth in DEPTHS)} grid points total")

    print("⏳ Generating Argo float data...")
    floats = generate_argo_floats()
    with open(os.path.join(out_dir, "floats.json"), "w") as f:
        json.dump(floats, f)
    print(f"✅ floats.json written — {len(floats)} floats")

    print("\n🌊 Data generation complete.")
