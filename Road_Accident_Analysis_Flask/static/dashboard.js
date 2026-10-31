const chartInstances = {};
let accidentMap;
let accidentLayer;
let hotspotLayer;
let filterTimer;

const filterIds = ["stateFilter", "cityFilter", "severityFilter", "causeFilter", "startDate", "endDate"];

function queryString() {
  const params = new URLSearchParams();
  const mapping = {
    stateFilter: "state", cityFilter: "city", severityFilter: "severity",
    causeFilter: "cause", startDate: "start_date", endDate: "end_date"
  };
  filterIds.forEach(id => {
    const value = document.getElementById(id).value;
    if (value && value !== "All") params.set(mapping[id], value);
  });
  return params.toString();
}

async function getJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json();
}

function fillSelect(id, values) {
  const select = document.getElementById(id);
  const current = select.value;
  select.innerHTML = '<option value="All">All</option>';
  values.forEach(value => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  });
  if ([...select.options].some(option => option.value === current)) select.value = current;
}

async function loadFilters() {
  const data = await getJSON("/api/filters");
  fillSelect("stateFilter", data.states);
  fillSelect("cityFilter", data.cities);
  fillSelect("severityFilter", data.severities);
  fillSelect("causeFilter", data.causes);
  document.getElementById("startDate").min = data.min_date;
  document.getElementById("startDate").max = data.max_date;
  document.getElementById("endDate").min = data.min_date;
  document.getElementById("endDate").max = data.max_date;
}

function numberFormat(value) {
  return Number(value || 0).toLocaleString("en-IN");
}

function renderChart(id, type, data, horizontal = false) {
  const canvas = document.getElementById(id);
  if (chartInstances[id]) chartInstances[id].destroy();
  chartInstances[id] = new Chart(canvas, {
    type,
    data: {
      labels: data.labels || [],
      datasets: [{
        label: "Accident records",
        data: data.values || [],
        backgroundColor: type === "line" ? "rgba(35,133,168,.14)" :
          ["#2c7da0", "#61a5c2", "#f4a261", "#e76f51", "#6c8ebf", "#8ab17d", "#b07aa1", "#d4a72c", "#718096", "#56a3a6"],
        borderColor: type === "line" ? "#2385a8" : "#ffffff",
        borderWidth: type === "line" ? 2 : 1,
        fill: type === "line",
        tension: .28,
        borderRadius: type === "bar" ? 5 : 0
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: horizontal ? "y" : "x",
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false }, ticks: { color: "#7b8798", maxRotation: 45 } },
        y: { beginAtZero: true, grid: { color: "#edf1f5" }, ticks: { color: "#7b8798" } }
      }
    }
  });
}

function renderHotspots(rows) {
  const body = document.getElementById("hotspotTable");
  document.getElementById("hotspotCount").textContent = `${rows.length} clusters shown`;
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="7" class="text-center muted py-4">No DBSCAN hotspots in the selected records.</td></tr>';
    return;
  }
  body.innerHTML = rows.map(row => `
    <tr>
      <td><span class="cluster-pill">${row.cluster_id}</span></td>
      <td>${numberFormat(row.accident_count)}</td>
      <td>${numberFormat(row.fatal_accidents)}</td>
      <td>${escapeHTML(row.city)}</td><td>${escapeHTML(row.state)}</td>
      <td>${Number(row.center_latitude).toFixed(5)}</td>
      <td>${Number(row.center_longitude).toFixed(5)}</td>
    </tr>`).join("");
}

function renderRecords(rows, total) {
  const body = document.getElementById("recordsTable");
  document.getElementById("recordCount").textContent = `Showing ${rows.length} of ${numberFormat(total)} records`;
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="10" class="text-center muted py-4">No records match these filters.</td></tr>';
    return;
  }
  body.innerHTML = rows.map(row => {
    const severity = String(row.accident_severity || "").toLowerCase();
    const severityClass = severity === "fatal" ? "sev-fatal" : severity === "major" ? "sev-major" : "sev-minor";
    return `<tr>
      <td>${escapeHTML(row.accident_id)}</td><td>${escapeHTML(row.city)}</td>
      <td>${escapeHTML(row.state)}</td><td>${escapeHTML(row.date)}</td>
      <td>${escapeHTML(row.time)}</td><td><span class="badge-severity ${severityClass}">${escapeHTML(severity)}</span></td>
      <td>${escapeHTML(row.cause)}</td><td>${escapeHTML(row.road_type)}</td>
      <td>${numberFormat(row.casualties)}</td>
      <td>${Number(row.cluster_id) < 0 ? "Noise" : `<span class="cluster-pill">${row.cluster_id}</span>`}</td>
    </tr>`;
  }).join("");
}

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  }[char]));
}

function initMap() {
  if (accidentMap) return;
  accidentMap = L.map("map").setView([22.5, 79.0], 5);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18, attribution: '&copy; OpenStreetMap contributors'
  }).addTo(accidentMap);
  accidentLayer = L.layerGroup().addTo(accidentMap);
  hotspotLayer = L.layerGroup().addTo(accidentMap);
}

async function renderMap() {
  initMap();
  const data = await getJSON(`/api/map?${queryString()}`);
  accidentLayer.clearLayers();
  hotspotLayer.clearLayers();

  data.points.forEach(point => {
    const color = point.accident_severity === "fatal" ? "#bd3544" :
      point.accident_severity === "major" ? "#e58a36" : "#3185a8";
    L.circleMarker([point.latitude, point.longitude], {
      radius: 3.5, color, fillColor: color, fillOpacity: .55, weight: 1
    }).bindPopup(`<b>${escapeHTML(point.city)}, ${escapeHTML(point.state)}</b><br>
      Severity: ${escapeHTML(point.accident_severity)}<br>
      Cause: ${escapeHTML(point.cause)}<br>
      Cluster: ${Number(point.cluster_id) < 0 ? "Noise" : point.cluster_id}`)
      .addTo(accidentLayer);
  });

  data.hotspots.forEach(hotspot => {
    L.circle([hotspot.latitude, hotspot.longitude], {
      radius: 350, color: "#d97706", weight: 2, fillColor: "#f59e0b", fillOpacity: .2
    }).bindPopup(`<b>DBSCAN Cluster ${hotspot.cluster_id}</b><br>
      Accidents: ${numberFormat(hotspot.accident_count)}<br>
      Fatal accidents: ${numberFormat(hotspot.fatal_accidents)}<br>
      City: ${escapeHTML(hotspot.city)}`)
      .addTo(hotspotLayer);
  });

  const allPoints = data.points;
  if (allPoints.length) {
    const bounds = L.latLngBounds(allPoints.map(p => [p.latitude, p.longitude]));
    accidentMap.fitBounds(bounds.pad(.08), { maxZoom: 8 });
  }
}

async function refreshDashboard() {
  try {
    const data = await getJSON(`/api/dashboard?${queryString()}`);
    const k = data.kpis;
    document.getElementById("kpiTotal").textContent = numberFormat(k.total);
    document.getElementById("kpiFatal").textContent = numberFormat(k.fatal);
    document.getElementById("kpiCities").textContent = numberFormat(k.cities);
    document.getElementById("kpiClusters").textContent = numberFormat(k.clusters);
    document.getElementById("kpiCasualties").textContent = numberFormat(k.casualties);
    document.getElementById("kpiRisk").textContent = Number(k.avg_risk || 0).toFixed(3);

    const c = data.charts;
    renderChart("severityChart", "doughnut", c.severity || {});
    renderChart("causeChart", "bar", c.causes || {}, true);
    renderChart("monthlyChart", "line", c.monthly || {});
    renderChart("hourlyChart", "bar", c.hourly || {});
    renderChart("citiesChart", "bar", c.cities || {}, true);
    renderChart("weatherChart", "doughnut", c.weather || {});
    renderChart("roadChart", "bar", c.road_types || {}, true);
    renderHotspots(data.hotspots || []);
    renderRecords(data.records || [], data.total_records || 0);
    await renderMap();
  } catch (error) {
    console.error(error);
    alert(`Unable to load dashboard data: ${error.message}`);
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  try {
    await loadFilters();
    await refreshDashboard();
  } catch (error) {
    console.error(error);
    alert(`Unable to initialize dashboard: ${error.message}`);
  }

  filterIds.forEach(id => {
    document.getElementById(id).addEventListener("change", () => {
      clearTimeout(filterTimer);
      filterTimer = setTimeout(refreshDashboard, 180);
    });
  });

  document.getElementById("resetBtn").addEventListener("click", () => {
    filterIds.forEach(id => {
      const element = document.getElementById(id);
      element.value = element.tagName === "SELECT" ? "All" : "";
    });
    refreshDashboard();
  });
});
