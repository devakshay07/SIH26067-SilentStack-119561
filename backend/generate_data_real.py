"""
generate_data_real.py
Replace synthetic data with REAL NetCDF ocean model files and Argo CSV/text data.

Run this once to regenerate model.json and floats.json from your actual data.
Then restart the API — the frontend requires zero changes.

Requirements:
    pip install xarray netcdf4 scipy pandas numpy

Expected input files:
    real_data/model_temperature.nc   — NetCDF ocean model (temperature)
    real_data/model_salinity.nc      — NetCDF ocean model (salinity)
    real_data/model_chlorophyll.nc   — NetCDF ocean model (chlorophyll)
    real_data/argo_floats.csv        — Argo float observations (CSV/text)
"""

import json
import os
import numpy as np
import pandas as pd
import xarray as xr
from scipy.interpolate import RegularGridInterpolator

# ─── CONFIG ──────────────────────────────────────────────
# Adjust these to match your NetCDF variable names
NC_VAR_MAP = {
    "temperature":  ("real_data/model_temperature.nc",  "thetao"),   # or "temp", "sst", "TEMP"
    "salinity":     ("real_data/model_salinity.nc",     "so"),        # or "salt", "SAL"
    "chlorophyll":  ("real_data/model_chlorophyll.nc",  "chl"),       # or "CHL", "chlor_a"
}

# Name of coordinate dimensions in YOUR NetCDF file — check with print(ds) below
NC_LAT_DIM  = "latitude"   # could be "lat", "nav_lat", "y"
NC_LON_DIM  = "longitude"  # could be "lon", "nav_lon", "x"
NC_DEPTH_DIM = "depth"     # could be "lev", "deptht", "z_t"
NC_TIME_DIM  = "time"      # could be "time_counter"

# Output depth levels (metres) — must exist in your model
DEPTHS = [0, 50, 100, 200, 500, 1000]

# Output grid resolution (degrees) — coarser = faster rendering
GRID_STEP = 0.5

# India EEZ bounding box
LAT_RANGE = (0, 25)
LON_RANGE = (60, 100)
# ─────────────────────────────────────────────────────────


def inspect_netcdf(path):
    """
    Call this first to see what's inside your NetCDF file.
    It will print dimensions, variables, and coordinates.
    """
    ds = xr.open_dataset(path)
    print("\n" + "="*60)
    print(f"FILE: {path}")
    print(ds)
    print("\nCoordinates:", list(ds.coords))
    print("Variables:  ", list(ds.data_vars))
    print("Dimensions: ", dict(ds.dims))
    ds.close()


def extract_model_field(nc_path, var_name, target_depths, lat_range, lon_range, grid_step):
    """
    Reads a NetCDF file, crops to India EEZ, regrids to uniform grid,
    and returns a dict of {day: {depth: [{"lat": x, "lon": x, "value": x}, ...]}}
    """
    ds = xr.open_dataset(nc_path)

    # Crop to India EEZ
    ds = ds.sel(
        **{
            NC_LAT_DIM:  slice(lat_range[0], lat_range[1]),
            NC_LON_DIM:  slice(lon_range[0], lon_range[1]),
        }
    )

    # Build uniform output grid
    out_lats = np.arange(lat_range[0], lat_range[1] + grid_step, grid_step)
    out_lons = np.arange(lon_range[0], lon_range[1] + grid_step, grid_step)

    time_steps = ds[NC_TIME_DIM].values
    # Take last 7 time steps (days)
    time_steps = time_steps[-7:]

    result = {}

    for t in time_steps:
        day_str = str(t)[:10]   # "2026-09-30"
        result[day_str] = {}

        for depth_m in target_depths:
            result[day_str][str(depth_m)] = {v: [] for v in ["temperature", "salinity", "chlorophyll"]}

            # Select nearest depth level
            data_slice = ds[var_name].sel(
                **{NC_TIME_DIM: t, NC_DEPTH_DIM: depth_m},
                method="nearest"
            )

            # Get native grid
            native_lats = data_slice[NC_LAT_DIM].values.astype(float)
            native_lons = data_slice[NC_LON_DIM].values.astype(float)
            values = data_slice.values.astype(float)

            # Fill NaN (land) with np.nan, skip during output
            values = np.where(np.isnan(values), np.nan, values)

            # Interpolate to uniform output grid
            try:
                interp = RegularGridInterpolator(
                    (native_lats, native_lons), values,
                    method="linear", bounds_error=False, fill_value=np.nan
                )
                for lat in out_lats:
                    for lon in out_lons:
                        val = float(interp([[lat, lon]])[0])
                        if not np.isnan(val):
                            result[day_str][str(depth_m)]["temperature"].append(
                                {"lat": round(float(lat), 2),
                                 "lon": round(float(lon), 2),
                                 "value": round(val, 3)}
                            )
            except Exception as e:
                print(f"  ⚠ Interpolation failed at {day_str}/{depth_m}m: {e}")

    ds.close()
    return result


def extract_argo_floats(csv_path):
    """
    Reads Argo float CSV/text data.

    Expected CSV columns (adjust MAP below if different):
        PLATFORM_NUMBER, LATITUDE, LONGITUDE, JULD (date),
        PRES (pressure/depth), TEMP (temperature), PSAL (salinity), DOXY (optional)

    This is the standard Argo GDAC format.
    """
    df = pd.read_csv(csv_path, delimiter=",", skipinitialspace=True,
                     na_values=["", "NaN", "99999.0", "99999"])

    # Column name mapping — edit if your file uses different names
    COL_MAP = {
        "id":    "PLATFORM_NUMBER",
        "lat":   "LATITUDE",
        "lon":   "LONGITUDE",
        "date":  "JULD",           # or "date", "TIME"
        "depth": "PRES",           # pressure in dbar ≈ depth in metres
        "temp":  "TEMP",
        "sal":   "PSAL",
        "chl":   "CHLA",           # may not exist — will default to 0
    }

    floats_out = []
    grouped = df.groupby(COL_MAP["id"])

    for float_id, group in grouped:
        group = group.dropna(subset=[COL_MAP["depth"], COL_MAP["temp"]])
        group = group.sort_values(COL_MAP["depth"])

        lat = float(group[COL_MAP["lat"]].iloc[0])
        lon = float(group[COL_MAP["lon"]].iloc[0])
        last_date = str(group[COL_MAP["date"]].iloc[-1])[:10]

        profile = []
        for _, row in group.iterrows():
            profile.append({
                "depth":       round(float(row[COL_MAP["depth"]]), 1),
                "temperature": round(float(row[COL_MAP["temp"]]), 3),
                "salinity":    round(float(row[COL_MAP["sal"]]), 3),
                "chlorophyll": round(float(row.get(COL_MAP["chl"], 0) or 0), 4),
            })

        floats_out.append({
            "id":        str(float_id),
            "lat":       round(lat, 4),
            "lon":       round(lon, 4),
            "region":    "Real Argo Observation",
            "depth_max": max(p["depth"] for p in profile),
            "cycle":     int(group.shape[0]),
            "last_seen": last_date,
            "profile":   profile,
        })

    return floats_out


if __name__ == "__main__":
    import sys

    # ── Step 0: Inspect your files first ──────────────────
    # Uncomment these lines to print what's inside your NetCDF files
    # inspect_netcdf("real_data/model_temperature.nc")
    # inspect_netcdf("real_data/model_salinity.nc")

    out_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(out_dir, exist_ok=True)

    # ── Step 1: Process model fields ──────────────────────
    combined_model = {}

    for var, (nc_path, nc_var) in NC_VAR_MAP.items():
        if not os.path.exists(nc_path):
            print(f"⚠  Skipping {var} — file not found: {nc_path}")
            continue

        print(f"⏳ Extracting {var} from {nc_path}...")
        fields = extract_model_field(
            nc_path, nc_var, DEPTHS, LAT_RANGE, LON_RANGE, GRID_STEP
        )

        # Merge into combined dict
        for day, depth_data in fields.items():
            if day not in combined_model:
                combined_model[day] = {}
            for depth_key, _ in depth_data.items():
                if depth_key not in combined_model[day]:
                    combined_model[day][depth_key] = {
                        "temperature": [], "salinity": [], "chlorophyll": []
                    }
                combined_model[day][depth_key][var] = fields[day][depth_key]["temperature"]

        print(f"  ✅ {var}: {len(fields)} time steps processed")

    with open(os.path.join(out_dir, "model.json"), "w") as f:
        json.dump(combined_model, f)
    print(f"\n✅ model.json written with real data")

    # ── Step 2: Process Argo floats ───────────────────────
    argo_path = "real_data/argo_floats.csv"
    if os.path.exists(argo_path):
        print(f"\n⏳ Extracting Argo floats from {argo_path}...")
        floats = extract_argo_floats(argo_path)
        with open(os.path.join(out_dir, "floats.json"), "w") as f:
            json.dump(floats, f)
        print(f"✅ floats.json written — {len(floats)} floats")
    else:
        print(f"⚠  Argo CSV not found at {argo_path} — keeping existing floats.json")

    print("\n🌊 Real data processing complete. Restart the API to serve it.")
