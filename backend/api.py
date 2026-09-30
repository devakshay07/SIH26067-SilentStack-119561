"""
api.py — FastAPI backend for INCOIS 3D Ocean Visualization
Endpoints:
  GET /api/model?var=temperature&depth=50&day=2026-09-30
  GET /api/floats
  GET /api/profile?float_id=ARG_6900000
  GET /api/meta
"""

import json
import math
import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

app = FastAPI(
    title="INCOIS Ocean Viz API",
    description="Serves ocean model fields and Argo float data for 3D visualization.",
    version="1.0.0"
)

# Allow frontend to call API from any origin (required for local dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# --- Load data at startup (cache in memory) ---
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

with open(os.path.join(DATA_DIR, "model.json")) as f:
    MODEL_DATA = json.load(f)

with open(os.path.join(DATA_DIR, "floats.json")) as f:
    FLOATS_DATA = json.load(f)

# Build float lookup index for O(1) access
FLOAT_INDEX = {fl["id"]: fl for fl in FLOATS_DATA}

VALID_VARS = ["temperature", "salinity", "chlorophyll", "currents"]
VALID_DEPTHS = [0, 50, 100, 200, 500, 1000]
VALID_DAYS = list(MODEL_DATA.keys())


@app.get("/api/meta")
def get_metadata():
    """Returns available variables, depths, and time steps."""
    return {
        "variables": VALID_VARS,
        "depths_m": VALID_DEPTHS,
        "days": VALID_DAYS,
        "float_count": len(FLOATS_DATA),
        "lat_range": [0, 25],
        "lon_range": [60, 100],
        "description": "India EEZ — Arabian Sea + Bay of Bengal + Indian Ocean"
    }


@app.get("/api/model")
def get_model_field(
    var: str = Query("temperature", description="Variable name"),
    depth: int = Query(0, description="Depth in metres"),
    day: str = Query("2026-09-30", description="Date (YYYY-MM-DD)")
):
    """Returns the ocean model grid for a given variable, depth, and day."""
    if var not in VALID_VARS:
        raise HTTPException(400, f"Invalid variable. Choose from: {VALID_VARS}")
    if depth not in VALID_DEPTHS:
        raise HTTPException(400, f"Invalid depth. Choose from: {VALID_DEPTHS}")
    if day not in VALID_DAYS:
        raise HTTPException(400, f"Invalid day. Choose from: {VALID_DAYS}")

    if var == "currents":
        base_grid = MODEL_DATA.get(day, {}).get(str(depth), {}).get("temperature", [])
        grid = []
        for pt in base_grid:
            start_lat, start_lon = pt["lat"], pt["lon"]
            
            # Generate a curved streamline (Euler integration)
            path = []
            curr_lat, curr_lon = start_lat, start_lon
            
            # Record starting magnitude for color mapping
            d_lat0 = curr_lat - 15.0
            d_lon0 = curr_lon - 65.0
            dist0 = math.sqrt(d_lat0**2 + d_lon0**2) + 0.1
            speed0 = max(0.05, 1.2 - (dist0 * 0.04))
            # Scale to actual realistic ocean velocities (0.1 to 1.5 m/s)
            mag = speed0 * (dist0 / 10.0 + 0.5) 
            
            for _ in range(5): # 5 curve segments
                path.append({"lat": curr_lat, "lon": curr_lon})
                
                # Gyre math: clockwise around (15N, 65E)
                d_lat = curr_lat - 15.0
                d_lon = curr_lon - 65.0
                dist = math.sqrt(d_lat**2 + d_lon**2) + 0.1
                
                # U is longitude change, V is latitude change
                # For clockwise: flow moves East (positive U) when North of center (d_lat > 0)
                # flow moves South (negative V) when East of center (d_lon > 0)
                u = d_lat * 0.1  # scale down to degrees-per-step
                v = -d_lon * 0.1
                
                curr_lon += u
                curr_lat += v
                
            grid.append({"lat": start_lat, "lon": start_lon, "value": round(mag, 3), "path": path})
    else:
        grid = MODEL_DATA[day][str(depth)][var]

    # Compute stats for colorbar rendering
    values = [p["value"] for p in grid] if grid else [0]
    return {
        "variable": var,
        "depth_m": depth,
        "day": day,
        "count": len(grid),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "mean": round(sum(values) / len(values), 3),
        "grid": grid
    }


@app.get("/api/floats")
def get_floats():
    """Returns all Argo float positions (without full profiles for performance)."""
    return [
        {
            "id": fl["id"],
            "lat": fl["lat"],
            "lon": fl["lon"],
            "region": fl["region"],
            "depth_max": fl["depth_max"],
            "cycle": fl["cycle"],
            "last_seen": fl["last_seen"]
        }
        for fl in FLOATS_DATA
    ]


@app.get("/api/profile")
def get_profile(float_id: str = Query(..., description="Float ID e.g. ARG_6900000")):
    """Returns the full depth profile for a specific Argo float."""
    if float_id not in FLOAT_INDEX:
        raise HTTPException(404, f"Float '{float_id}' not found.")
    fl = FLOAT_INDEX[float_id]
    return {
        "id": fl["id"],
        "lat": fl["lat"],
        "lon": fl["lon"],
        "region": fl["region"],
        "last_seen": fl["last_seen"],
        "cycle": fl["cycle"],
        "profile": fl["profile"]
    }


# Serve the frontend at root
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
