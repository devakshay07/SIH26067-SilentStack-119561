/**
 * app.js — INCOIS 3D Ocean Visualization Platform
 * Core application logic: globe, data rendering, interactions
 */

const API = window.location.hostname === "localhost" ? "http://localhost:8000/api" : "/api";

// --- App State ---
const state = {
  variable: "temperature",
  isosurface: false,
  depth: 0,
  dayIndex: 6,          // latest day by default
  days: [],
  playing: false,
  playInterval: null,
  opacity: 0.85,
  selectedFloat: null,
  floats: [],
  currentGridData: null,
  profileVar: "temperature",
};

// Variable display configs
const VAR_CONFIG = {
  temperature: {
    label: "Temperature (°C)",
    unit: "°C",
    gradient: ["#0000ff", "#00aaff", "#00ffff", "#ffff00", "#ff6600", "#ff0000"],
  },
  salinity: {
    label: "Salinity (PSU)",
    unit: "PSU",
    gradient: ["#f0f8ff", "#87ceeb", "#4682b4", "#00008b", "#000033"],
  },
  chlorophyll: {
    label: "Chlorophyll (mg/m³)",
    unit: "mg/m³",
    gradient: ["#000033", "#003300", "#006600", "#00aa00", "#aaff00", "#ffffff"],
  },
  currents: {
    label: "Velocity (m/s)",
    unit: "m/s",
    gradient: ["#ffffff", "#00d4ff", "#0000ff", "#ff00ff"],
  },
};

// =============================================
// LOOP 1 — Initialize Cesium Globe
// =============================================

// Restored the Ion token as requested
Cesium.Ion.defaultAccessToken =
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiJlYWE1OWIxNy1mMWZiLTQzYjYtYTQ5NS04YzE4MDAwYmI0YjEiLCJpZCI6MjU5Mzk3LCJpYXQiOjE3MzMwMDUyMTJ9.e_Y9WjRxSZNGEWkqBfvGMwb1MMZqv1r-MDBfhiJ8pnY";

const viewer = new Cesium.Viewer("cesiumContainer", {
  terrainProvider: new Cesium.EllipsoidTerrainProvider(),
  baseLayerPicker: true, // Enabled! This adds the map selection dropdown menu
  navigationHelpButton: false,
  sceneModePicker: false,
  homeButton: false,
  geocoder: false,
  animation: false,
  timeline: false,
  fullscreenButton: false,
  infoBox: false,
  selectionIndicator: false,
  creditContainer: document.createElement("div"),
});

// Set ArcGIS World Imagery as the default map in the dropdown
const pickerViewModel = viewer.baseLayerPicker.viewModel;
const esriModel = pickerViewModel.imageryProviderViewModels.find(
  model => model.name.toLowerCase().includes("esri world imagery") || model.name.toLowerCase().includes("arcgis")
);
if (esriModel) {
  pickerViewModel.selectedImagery = esriModel;
}

// Removed the black override so the actual map tiles show through normally
viewer.scene.backgroundColor = Cesium.Color.fromCssColorString("#0a0f1e");
viewer.scene.globe.showGroundAtmosphere = true; // Enabled to make the globe look realistic

// Camera: center on India's ocean region
viewer.camera.flyTo({
  destination: Cesium.Cartesian3.fromDegrees(80, 12, 5500000),
  orientation: { heading: 0, pitch: Cesium.Math.toRadians(-65), roll: 0 },
  duration: 2,
});

// =============================================
// LOOP 2 — Color Utilities
// =============================================

function hexToRgb(hex) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return [r, g, b];
}

function interpolateColor(gradient, t) {
  t = Math.max(0, Math.min(1, t));
  const seg = (gradient.length - 1) * t;
  const idx = Math.floor(seg);
  const frac = seg - idx;
  const c1 = hexToRgb(gradient[Math.min(idx, gradient.length - 1)]);
  const c2 = hexToRgb(gradient[Math.min(idx + 1, gradient.length - 1)]);
  return [
    Math.round(c1[0] + (c2[0] - c1[0]) * frac),
    Math.round(c1[1] + (c2[1] - c1[1]) * frac),
    Math.round(c1[2] + (c2[2] - c1[2]) * frac),
  ];
}

function valueToColor(value, min, max, variable) {
  if (max === min || isNaN(value) || isNaN(min) || isNaN(max)) {
    return new Cesium.Color(1, 1, 1, state.opacity);
  }
  let t = (value - min) / (max - min);
  t = Math.max(0, Math.min(1, t)); // clamp
  const config = VAR_CONFIG[variable] || VAR_CONFIG.temperature;
  const [r, g, b] = interpolateColor(config.gradient, t);
  return new Cesium.Color(r / 255, g / 255, b / 255, state.opacity);
}

// =============================================
// LOOP 3 — Render Ocean Model Grid
// =============================================

let MODEL_CACHE = {}; // Global cache for client-side CSV processing
let pointPrimitives = null;

const DEPTH_STEPS = [0, 50, 100, 200, 500, 1000];

async function loadModelField() {
  showLoading(true);
  const day = state.days[state.dayIndex];
  
  let dataToRender;
  
  if (state.isosurface) {
    // 3D Volume Render: Fetch all depths concurrently
    const promises = DEPTH_STEPS.map(d => fetch(`${API}/model?var=${state.variable}&depth=${d}&day=${day}`).then(r => r.json()));
    const results = await Promise.all(promises);
    
    // Merge grids and keep track of individual depths
    let mergedGrid = [];
    let overallMin = Infinity;
    let overallMax = -Infinity;
    
    results.forEach((res, idx) => {
      overallMin = Math.min(overallMin, res.min);
      overallMax = Math.max(overallMax, res.max);
      const d = DEPTH_STEPS[idx];
      if (res.grid) {
        res.grid.forEach(pt => {
          mergedGrid.push({ lat: pt.lat, lon: pt.lon, value: pt.value, depth: d });
        });
      }
    });
    
    dataToRender = { 
      min: overallMin, 
      max: overallMax, 
      grid: mergedGrid, 
      variable: state.variable,
      depth_m: "3D Volume",
      day: day,
      count: mergedGrid.length
    };
  } else {
    // 2D Slice (Normal mode)
    const url = `${API}/model?var=${state.variable}&depth=${state.depth}&day=${day}`;
    const res = await fetch(url);
    const data = await res.json();
    
    // Add current depth to grid points so renderGrid works
    if (data.grid) {
      data.grid.forEach(pt => pt.depth = state.depth);
    }
    dataToRender = data;
  }

  state.currentGridData = dataToRender;
  renderGrid(dataToRender);
  updateColorbar(dataToRender.min, dataToRender.max);
  updateStats(dataToRender);
  showLoading(false);
}

let polylinePrimitives = null;

function renderGrid(data) {
  // Remove old primitives
  if (pointPrimitives) viewer.scene.primitives.remove(pointPrimitives);
  if (polylinePrimitives) viewer.scene.primitives.remove(polylinePrimitives);

  const { min, max, grid, variable } = data;
  
  if (variable === "currents") {
    // RENDER VECTORS (Curved Streamlines)
    const collection = new Cesium.PolylineCollection();
    for (const pt of grid) {
      if (!pt.path) continue;
      
      const zOffset = (state.isosurface && pt.depth !== undefined) ? -(pt.depth * 200) : 100;
      
      // Flatten the path into [lon, lat, height, lon, lat, height...]
      const flatPositions = [];
      for (const node of pt.path) {
        flatPositions.push(node.lon, node.lat, zOffset);
      }
      
      try {
        const color = valueToColor(pt.value, min, max, variable);
        color.alpha = state.opacity;
        
        collection.add({
          positions: Cesium.Cartesian3.fromDegreesArrayHeights(flatPositions),
          width: 4, // Slightly thicker for realism
          material: Cesium.Material.fromType("PolylineArrow", {
            color: color
          })
        });
      } catch (e) {
        console.warn("Failed to add streamline:", e);
      }
    }
    polylinePrimitives = viewer.scene.primitives.add(collection);
  } else {
    // RENDER POINTS (Scalar data)
    const collection = new Cesium.PointPrimitiveCollection({ capacity: grid.length });

    for (const pt of grid) {
      let alpha = state.opacity;
      let size = 7;
      
      if (state.isosurface) {
        if (max !== min) {
          const normalized = (pt.value - min) / (max - min);
          const extremity = Math.abs(normalized - 0.5); 
          alpha = 0.05 + (extremity * 2 * 0.95); 
          size = 5 + (extremity * 2 * 10); 
        } else {
          size = 10;
          alpha = 0.5;
        }
      }
      
      let zOffset = 100;
      if (state.isosurface && pt.depth !== undefined) {
         zOffset = -(pt.depth * 200); 
      }
      
      try {
        const color = valueToColor(pt.value, min, max, variable);
        color.alpha = alpha; 
        
        collection.add({
          position: Cesium.Cartesian3.fromDegrees(pt.lon, pt.lat, zOffset),
          color: color,
          pixelSize: size,
        });
      } catch (e) {
        console.warn("Failed to add point:", e);
      }
    }

    pointPrimitives = viewer.scene.primitives.add(collection);
  }
}

// =============================================
// LOOP 4 — Argo Float Markers
// =============================================

let floatEntities = {};

async function loadFloats() {
  const res = await fetch(`${API}/floats`);
  state.floats = await res.json();

  renderFloatList(state.floats);

  for (const fl of state.floats) {
    const entity = viewer.entities.add({
      id: fl.id,
      position: Cesium.Cartesian3.fromDegrees(fl.lon, fl.lat, 500),
      point: {
        pixelSize: 10,
        color: Cesium.Color.fromCssColorString("#00d4ff"),
        outlineColor: Cesium.Color.WHITE,
        outlineWidth: 1.5,
        heightReference: Cesium.HeightReference.NONE,
      },
      label: {
        text: fl.id.replace("ARG_", ""),
        font: "9px Inter",
        fillColor: Cesium.Color.WHITE,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 1,
        pixelOffset: new Cesium.Cartesian2(0, -16),
        show: false,
      },
    });
    floatEntities[fl.id] = entity;
  }
}

function renderFloatList(floats) {
  const list = document.getElementById("float-list");
  list.innerHTML = "";
  for (const fl of floats) {
    const item = document.createElement("div");
    item.className = "float-item";
    item.dataset.id = fl.id;
    item.innerHTML = `
      <div class="float-dot"></div>
      <div>
        <div class="float-id">${fl.id.replace("ARG_", "")}</div>
        <div class="float-region">${fl.region}</div>
      </div>`;
    item.addEventListener("click", () => selectFloat(fl.id));
    list.appendChild(item);
  }
  document.getElementById("float-count").textContent = floats.length;
}

// =============================================
// LOOP 5 — Float Click → Profile Panel
// =============================================

async function selectFloat(floatId) {
  // Deselect previous
  if (state.selectedFloat && floatEntities[state.selectedFloat]) {
    floatEntities[state.selectedFloat].point.color =
      Cesium.Color.fromCssColorString("#00d4ff");
    floatEntities[state.selectedFloat].label.show = false;
  }

  state.selectedFloat = floatId;

  // Highlight selected
  floatEntities[floatId].point.color = Cesium.Color.fromCssColorString("#ffaa00");
  floatEntities[floatId].point.pixelSize = 14;
  floatEntities[floatId].label.show = true;

  // Update sidebar selection
  document.querySelectorAll(".float-item").forEach((el) => {
    el.classList.toggle("selected", el.dataset.id === floatId);
  });

  // Fetch and render profile
  const res = await fetch(`${API}/profile?float_id=${floatId}`);
  const data = await res.json();
  renderProfile(data);

  // Fly camera to float
  viewer.camera.flyTo({
    destination: Cesium.Cartesian3.fromDegrees(data.lon, data.lat, 1200000),
    duration: 1.2,
  });
}

// =============================================
// LOOP 6 — Chart.js Depth Profile
// =============================================

let profileChart = null;

function renderProfile(data) {
  const panel = document.getElementById("profile-panel");
  panel.classList.add("visible");

  document.getElementById("profile-title").textContent =
    data.id.replace("ARG_", "");
  document.getElementById("profile-meta").innerHTML = `
    <strong>Region:</strong> ${data.region}<br>
    <strong>Position:</strong> ${data.lat.toFixed(3)}°N, ${data.lon.toFixed(3)}°E<br>
    <strong>Last Cycle:</strong> ${data.last_seen} &nbsp;|&nbsp; Cycle #${data.cycle}<br>
    <strong>Max Depth:</strong> 2000 m
  `;

  renderProfileChart(data.profile, state.profileVar);
  renderProfileTable(data.profile);
}

function renderProfileChart(profile, variable) {
  const labels = profile.map((p) => p.depth);
  const values = profile.map((p) => p[variable]);
  const cfg = VAR_CONFIG[variable];

  const ctx = document.getElementById("profileChart").getContext("2d");

  if (profileChart) profileChart.destroy();

  profileChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: values,
      datasets: [
        {
          label: cfg.label,
          data: profile.map((p) => ({ x: p[variable], y: p.depth })),
          borderColor: "#00d4ff",
          backgroundColor: "rgba(0,212,255,0.08)",
          borderWidth: 2,
          pointRadius: 4,
          pointBackgroundColor: "#00d4ff",
          tension: 0.35,
          fill: true,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.raw.x} ${cfg.unit} @ ${ctx.raw.y}m`,
          },
          backgroundColor: "#0d1529",
          borderColor: "#1e3a5f",
          borderWidth: 1,
          titleColor: "#7aa3c8",
          bodyColor: "#e8f4fd",
        },
      },
      scales: {
        x: {
          title: { display: true, text: cfg.label, color: "#7aa3c8", font: { size: 11 } },
          ticks: { color: "#7aa3c8", font: { size: 10 } },
          grid: { color: "rgba(30,58,95,0.5)" },
        },
        y: {
          title: { display: true, text: "Depth (m)", color: "#7aa3c8", font: { size: 11 } },
          reverse: true, // depth increases downward
          ticks: {
            color: "#7aa3c8",
            font: { size: 10 },
            callback: (v) => `${v}m`,
          },
          grid: { color: "rgba(30,58,95,0.5)" },
        },
      },
    },
  });
}

function renderProfileTable(profile) {
  const tbody = document.querySelector("#profile-table tbody");
  tbody.innerHTML = profile
    .map(
      (p) =>
        `<tr>
          <td>${p.depth}m</td>
          <td>${p.temperature.toFixed(2)}</td>
          <td>${p.salinity.toFixed(3)}</td>
          <td>${(p.chlorophyll || 0).toFixed(4)}</td>
        </tr>`
    )
    .join("");
}

// =============================================
// LOOP 7 — Colorbar
// =============================================

function updateColorbar(min, max) {
  const canvas = document.getElementById("colorbar");
  const ctx = canvas.getContext("2d");
  const gradient = ctx.createLinearGradient(0, canvas.height, 0, 0);
  const stops = VAR_CONFIG[state.variable].gradient;

  stops.forEach((color, i) => {
    gradient.addColorStop(i / (stops.length - 1), color);
  });

  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Labels
  document.getElementById("cb-max").textContent =
    `${max.toFixed(1)} ${VAR_CONFIG[state.variable].unit}`;
  document.getElementById("cb-mid").textContent =
    `${((min + max) / 2).toFixed(1)}`;
  document.getElementById("cb-min").textContent =
    `${min.toFixed(1)}`;
}

// =============================================
// LOOP 8 — Stats Panel
// =============================================

function updateStats(data) {
  document.getElementById("stat-var").textContent = data.variable;
  document.getElementById("stat-depth").textContent = String(data.depth_m).includes("3D") ? data.depth_m : `${data.depth_m} m`;
  document.getElementById("stat-day").textContent = data.day;
  document.getElementById("stat-points").textContent = data.count.toLocaleString();
  document.getElementById("stat-range").textContent =
    `${data.min.toFixed(1)} – ${data.max.toFixed(1)} ${VAR_CONFIG[data.variable].unit}`;
}

// =============================================
// LOOP 9 — UI Controls
// =============================================

function showLoading(show) {
  document.getElementById("loading").style.display = show ? "flex" : "none";
}

// Variable selector
document.getElementById("var-select").addEventListener("change", (e) => {
  state.variable = e.target.value;
  loadModelField();
});

// Depth slider
const depthSlider = document.getElementById("depth-slider");
const depthValues = [0, 50, 100, 200, 500, 1000];
depthSlider.max = depthValues.length - 1;
depthSlider.value = 0;

depthSlider.addEventListener("input", (e) => {
  state.depth = depthValues[parseInt(e.target.value)];
  document.getElementById("depth-display").textContent = `${state.depth} m`;
  loadModelField();
});

// Opacity slider
document.getElementById("opacity-slider").addEventListener("input", (e) => {
  state.opacity = parseFloat(e.target.value);
  document.getElementById("opacity-display").textContent =
    `${Math.round(state.opacity * 100)}%`;
  if (state.currentGridData) renderGrid(state.currentGridData);
});

// Time controls
document.getElementById("btn-prev").addEventListener("click", () => {
  state.dayIndex = Math.max(0, state.dayIndex - 1);
  updateTimeLabel();
  loadModelField();
});

document.getElementById("btn-next").addEventListener("click", () => {
  state.dayIndex = Math.min(state.days.length - 1, state.dayIndex + 1);
  updateTimeLabel();
  loadModelField();
});

// Play/Pause toggle for time animation
document.getElementById("btn-play").addEventListener("click", () => {
  if (state.playing) {
    clearInterval(state.playInterval);
    state.playing = false;
  } else {
    state.playing = true;
    state.playInterval = setInterval(() => {
      state.dayIndex = (state.dayIndex + 1) % state.days.length;
      updateTimeLabel();
      loadModelField();
    }, 2000);
  }
});

// =============================================
// Live Navbar Info (Time, Date, Location)
// =============================================
function setupNavbarInfo() {
  // Update time and date locally every second
  setInterval(() => {
    const now = new Date();
    document.getElementById("nav-time").textContent = now.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
    document.getElementById("nav-date").textContent = now.toLocaleDateString(undefined, {weekday: 'short', month: 'short', day: 'numeric'});
  }, 1000);

  // Fetch coarse location from IP
  fetch("https://ipapi.co/json/")
    .then(r => r.json())
    .then(data => {
      if (data.city && data.country_name) {
        document.getElementById("nav-location").textContent = `${data.city}, ${data.country_name}`;
      } else {
        document.getElementById("nav-location").textContent = "Offline/Local";
      }
    })
    .catch(() => {
      document.getElementById("nav-location").textContent = "Offline";
    });
}
setupNavbarInfo();

function updateTimeLabel() {
  document.getElementById("time-label").textContent = state.days[state.dayIndex] || "—";
}

// Profile variable tabs
document.querySelectorAll(".profile-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".profile-tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    state.profileVar = tab.dataset.var;
    if (state.selectedFloat) {
      // Re-render chart with new variable
      fetch(`${API}/profile?float_id=${state.selectedFloat}`)
        .then((r) => r.json())
        .then((data) => {
          renderProfileChart(data.profile, state.profileVar);
        });
    }
  });
});

// Close profile panel
document.getElementById("close-profile").addEventListener("click", () => {
  document.getElementById("profile-panel").classList.remove("visible");
  if (state.selectedFloat && floatEntities[state.selectedFloat]) {
    floatEntities[state.selectedFloat].point.color =
      Cesium.Color.fromCssColorString("#00d4ff");
    floatEntities[state.selectedFloat].point.pixelSize = 10;
    floatEntities[state.selectedFloat].label.show = false;
  }
  state.selectedFloat = null;
  document.querySelectorAll(".float-item").forEach((el) => el.classList.remove("selected"));
});

// Click on globe → select float
const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
handler.setInputAction((click) => {
  const picked = viewer.scene.pick(click.position);
  if (Cesium.defined(picked) && Cesium.defined(picked.id) && picked.id.id) {
    const floatId = picked.id.id;
    if (floatEntities[floatId]) {
      selectFloat(floatId);
    }
  }
}, Cesium.ScreenSpaceEventType.LEFT_CLICK);

// =============================================
// BOOT — Initialize application
// =============================================

async function init() {
  showLoading(true);

  // Fetch metadata first
  const meta = await fetch(`${API}/meta`).then((r) => r.json());
  state.days = meta.days;
  state.dayIndex = meta.days.length - 1;
  updateTimeLabel();

  // Parallel load
  await Promise.all([loadModelField(), loadFloats()]);

  showLoading(false);
  document.getElementById("status-badge").innerHTML = `<svg width="8" height="8" viewBox="0 0 8 8" style="vertical-align: middle; margin-right: 4px;"><circle cx="4" cy="4" r="4" fill="currentColor"/></svg> LIVE`;
}

init().catch((err) => {
  console.error("Init failed:", err);
  document.getElementById("loading").innerHTML = `
    <p style="color:#ff4444"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: middle; margin-right: 4px;"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg> API unreachable. Start the backend:<br><code>cd backend && python api.py</code></p>`;
});


// =============================================
// Client-Side CSV Upload & Processing (Vercel Scalable)
// =============================================
document.getElementById("csv-upload")?.addEventListener("change", function(e) {
  const file = e.target.files[0];
  if (!file) return;

  const status = document.getElementById("upload-status");
  status.style.display = "block";
  status.textContent = "Parsing CSV locally...";
  showLoading(true);
  document.getElementById("loading-msg").textContent = "Processing raw dataset...";

  Papa.parse(file, {
    header: true,
    dynamicTyping: true,
    skipEmptyLines: true,
    complete: function(results) {
      status.textContent = "Cleaning & Mapping data...";
      const data = results.data;
      
      // Look for standard column names (case insensitive)
      const getCol = (row, names) => {
        const key = Object.keys(row).find(k => names.some(n => k.toLowerCase().includes(n)));
        return key ? row[key] : null;
      };

      const customFloatsMap = new Map();
      let minLat = 90, maxLat = -90, minLon = 180, maxLon = -180;
      const datesSet = new Set();

      data.forEach(row => {
        const lat = getCol(row, ["lat"]);
        const lon = getCol(row, ["lon", "lng"]);
        const temp = getCol(row, ["temp", "sst"]);
        let depth = getCol(row, ["depth", "pres"]);
        let time = getCol(row, ["time", "date", "timestamp"]);
        const floatId = getCol(row, ["platform", "id", "float"]) || "Custom_1";
        const sal = getCol(row, ["sal", "psal"]) || 35.0;

        // Skip invalid rows
        if (lat == null || lon == null || temp == null) return;
        if (depth == null) depth = 0;
        
        let dateStr = "Unknown Date";
        if (time) {
          const d = new Date(time);
          if (!isNaN(d)) dateStr = d.toISOString().split("T")[0];
        }
        datesSet.add(dateStr);

        minLat = Math.min(minLat, lat);
        maxLat = Math.max(maxLat, lat);
        minLon = Math.min(minLon, lon);
        maxLon = Math.max(maxLon, lon);

        if (!customFloatsMap.has(floatId)) {
          customFloatsMap.set(floatId, {
            id: `ARG_${floatId}`,
            lat: lat,
            lon: lon,
            region: "User Uploaded Data",
            depth_max: depth,
            cycle: 1,
            last_seen: dateStr,
            profile: []
          });
        }
        
        const fl = customFloatsMap.get(floatId);
        fl.depth_max = Math.max(fl.depth_max, depth);
        fl.cycle++;
        
        // Add to profile
        fl.profile.push({
          depth: Math.round(depth),
          temperature: temp,
          salinity: sal,
          chlorophyll: 0.0,
          date: dateStr
        });
      });

      const customFloats = Array.from(customFloatsMap.values());
      
      // Sort profiles by depth
      customFloats.forEach(f => {
        f.profile.sort((a, b) => a.depth - b.depth);
      });

      // Build simulated model grid from surface data (depth <= 15)
      const customDays = Array.from(datesSet).sort().slice(-7); // Keep last 7 days max for timeline
      if (customDays.length === 0) customDays.push("Unknown Date");
      
      const customModel = {};
      customDays.forEach(day => {
        customModel[day] = {};
        [0, 50, 100, 200, 500, 1000].forEach(d => {
          customModel[day][d.toString()] = { temperature: [], salinity: [], chlorophyll: [] };
        });
      });

      customFloats.forEach(f => {
        const surface = f.profile.find(p => p.depth <= 15) || f.profile[0];
        if (!surface) return;
        const day = customDays.includes(surface.date) ? surface.date : customDays[0];
        
        [0, 50, 100, 200, 500, 1000].forEach(dLevel => {
          // Find closest depth reading for this float
          let closest = f.profile[0];
          let minDiff = 9999;
          f.profile.forEach(p => {
            const diff = Math.abs(p.depth - dLevel);
            if (diff < minDiff) { minDiff = diff; closest = p; }
          });
          
          if (customModel[day][dLevel.toString()]) {
             customModel[day][dLevel.toString()].temperature.push({ lat: f.lat, lon: f.lon, value: closest.temperature });
             customModel[day][dLevel.toString()].salinity.push({ lat: f.lat, lon: f.lon, value: closest.salinity });
          }
        });
      });

      // Override application state globally
      state.floats = customFloats;
      MODEL_CACHE = customModel; // Using in-memory cache directly
      state.days = customDays;
      state.dayIndex = customDays.length - 1;

      // Re-render UI
      updateTimeLabel();
      renderFloatList(state.floats);
      
      // Plot floats on map
      viewer.entities.removeAll(); // Clear old floats
      floatEntities = {}; // Reset lookup map
      for (const fl of state.floats) {
        const entity = viewer.entities.add({
          id: fl.id,
          position: Cesium.Cartesian3.fromDegrees(fl.lon, fl.lat, 500),
          point: { pixelSize: 10, color: Cesium.Color.fromCssColorString("#00d4ff"), outlineColor: Cesium.Color.WHITE, outlineWidth: 1.5 },
          label: { text: fl.id.replace("ARG_", ""), font: "9px Inter", fillColor: Cesium.Color.WHITE, pixelOffset: new Cesium.Cartesian2(12, 0), show: false }
        });
        floatEntities[fl.id] = entity; // Rebuild lookup
      }

      // Fly camera to uploaded data bounding box
      viewer.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees((minLon+maxLon)/2, (minLat+maxLat)/2, 5500000),
        duration: 2
      });

      // Trick the loadModelField to use our cache
      const originalFetch = window.fetch;
      window.fetch = async (url, options) => {
        if (url.includes("/api/model")) {
          const params = new URLSearchParams(url.split("?")[1]);
          const varName = params.get("var");
          const depth = params.get("depth");
          const day = params.get("day");
          
          let points = [];
          if (MODEL_CACHE[day] && MODEL_CACHE[day][depth] && MODEL_CACHE[day][depth][varName]) {
            points = MODEL_CACHE[day][depth][varName];
          }
          
          let min = 999, max = -999;
          points.forEach(p => { min = Math.min(min, p.value); max = Math.max(max, p.value); });
          if(min===999) min=0; if(max===-999) max=1;
          
          return { json: async () => ({ min, max, grid: points, variable: varName, depth_m: parseInt(depth), day: day, count: points.length }) };
        }
        return originalFetch(url, options);
      };

      loadModelField(); // Re-render grid
      showLoading(false);
      status.textContent = `Success: Loaded ${customFloats.length} floats.`;
      setTimeout(() => { status.style.display = "none"; }, 4000);
    },
    error: function(err) {
      console.error(err);
      status.textContent = "Error parsing CSV.";
      showLoading(false);
    }
  });
});


// =============================================
// Float Search Functionality
// =============================================
document.getElementById("float-search")?.addEventListener("input", (e) => {
  const query = e.target.value.toLowerCase();
  const filtered = state.floats.filter(f => 
    f.id.toLowerCase().includes(query) || 
    f.region.toLowerCase().includes(query)
  );
  renderFloatList(filtered);
});

document.getElementById("isosurface-toggle")?.addEventListener("change", (e) => {
  state.isosurface = e.target.checked;
  const slider = document.getElementById("depth-slider");
  if (state.isosurface) {
    slider.style.opacity = "0.3";
    slider.disabled = true;
  } else {
    slider.style.opacity = "1";
    slider.disabled = false;
  }
  loadModelField();
});
