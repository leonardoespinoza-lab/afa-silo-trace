const state = {
  sites: [],
  dependencies: [],
  province: "Todas",
  department: "Todos",
  siteType: "Todos",
  ccp: "Todos",
  grain: "Todos",
  risk: "Todos",
  search: "",
  selectedSiteId: null,
  selectedSiloId: null,
  locatingSiteId: null,
  drawingSiloSiteId: null,
  drawingBoundarySiteId: null,
  boundaryDraft: [],
  currentUser: null,
  view: "dashboard",
  users: []
};

const riskOrder = ["Normal", "Atencion", "Riesgo", "Critico"];
const riskLabels = { Normal: "Normal", Atencion: "Atencion", Riesgo: "Riesgo", Critico: "Critico" };
const riskColors = { Normal: "#39ff88", Atencion: "#ffe35a", Riesgo: "#ff9a3d", Critico: "#ff4b5f" };
const grainLimits = { Maiz: 14.1, Trigo: 14.0, Soja: 12.9, Girasol: 8.0, Sorgo: 15.6 };
const sourceNote = "Demo con base SQLite local. La version productiva deberia importar plantas activas SISA/ARCA, CUIT, numero de planta y estado registral; luego relevar sobre imagen satelital el limite de cada acopio y la circunferencia real de cada silo.";

const map = L.map("map", { zoomControl: false }).setView([-32.9, -61.4], 7);
L.control.zoom({ position: "bottomright" }).addTo(map);
const satelliteLayer = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
  maxZoom: 19,
  attribution: "Tiles &copy; Esri"
});
const streetLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap"
});
satelliteLayer.addTo(map);
L.control.layers({ "Satelital": satelliteLayer, "Calles": streetLayer }, {}, { position: "bottomright" }).addTo(map);

const siteLayer = L.layerGroup().addTo(map);
const plantLayer = L.layerGroup().addTo(map);
const siloLayer = L.layerGroup().addTo(map);
let pendingLocationMarker = null;
let pendingLocation = null;
let liveWeatherSiteId = null;

async function boot() {
  bindLogin();
}

function bindLogin() {
  document.getElementById("loginForm").addEventListener("submit", async event => {
    event.preventDefault();
    const payload = formPayload(event.currentTarget);
    const response = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (!response.ok) {
      document.getElementById("loginError").hidden = false;
      document.getElementById("loginError").textContent = "Credenciales invalidas.";
      return;
    }
    const result = await response.json();
    state.currentUser = result.user;
    document.getElementById("loginScreen").hidden = true;
    document.getElementById("appShell").hidden = false;
    await loadAppData();
  });
}

async function loadAppData() {
  const response = await fetch("/api/sites");
  const payload = await response.json();
  const dependencyResponse = await fetch("/api/dependencies");
  const dependencyPayload = await dependencyResponse.json();
  applyAccess(payload.sites, dependencyPayload.dependencies);
  state.selectedSiteId = state.sites[0]?.id;
  state.selectedSiloId = state.sites[0]?.silos[0]?.id;
  bindControls();
  await loadUsers();
  applyRoleVisibility();
  renderAll();
  refreshLiveWeather(selectedSite());
}

function applyAccess(allSites, allDependencies) {
  const scopeType = state.currentUser?.scopeType || (state.currentUser?.role === "ccp" ? "site" : "national");
  const scopeValue = state.currentUser?.scopeValue || state.currentUser?.siteId;
  if (scopeType === "national") {
    state.sites = allSites;
    state.dependencies = allDependencies;
    return;
  }
  if (scopeType === "province") {
    state.sites = allSites.filter(site => site.province === scopeValue);
    state.dependencies = allDependencies.filter(dep => dep.province === scopeValue);
    return;
  }
  state.sites = allSites.filter(site => site.id === scopeValue);
  const assigned = state.sites[0];
  const ccpName = assigned?.name.replace("CCP ", "").replace("AFA ", "");
  state.dependencies = allDependencies.filter(dep => dep.parentSiteId === scopeValue || (ccpName && dep.town === assigned?.town));
}

function bindControls() {
  document.querySelectorAll("[data-view]").forEach(button => {
    button.addEventListener("click", () => setView(button.dataset.view));
  });
  document.getElementById("appShell").addEventListener("click", event => {
    const button = event.target.closest("[data-view]");
    if (button) setView(button.dataset.view);
  });
  ["provinceFilter", "departmentFilter", "siteTypeFilter", "ccpFilter", "grainFilter", "riskFilter"].forEach(id => {
    document.getElementById(id).addEventListener("change", event => {
      const key = id === "siteTypeFilter" ? "siteType" : id === "ccpFilter" ? "ccp" : id.replace("Filter", "");
      state[key] = event.target.value;
      if (id === "provinceFilter") state.department = "Todos";
      renderAll();
    });
  });
  document.getElementById("searchFilter").addEventListener("input", event => {
    state.search = event.target.value;
    renderAll();
  });
  document.getElementById("siteSelect").addEventListener("change", event => {
    state.selectedSiteId = event.target.value;
    const site = state.sites.find(item => item.id === state.selectedSiteId);
    state.selectedSiloId = site?.silos[0]?.id || null;
    renderAll();
  });
  document.getElementById("openSiteForm").addEventListener("click", () => {
    openModal("siteModal");
    const site = selectedSite();
    if (site) {
      document.querySelector("#siteForm [name='lat']").value = site.lat.toFixed(6);
      document.querySelector("#siteForm [name='lng']").value = site.lng.toFixed(6);
    }
  });
  document.getElementById("openDependencyForm").addEventListener("click", () => openModal("dependencyModal"));
  document.getElementById("siteForm").addEventListener("submit", submitSite);
  document.getElementById("dependencyForm").addEventListener("submit", submitDependency);
  document.getElementById("userForm").addEventListener("submit", submitUser);
  document.getElementById("openUserForm").addEventListener("click", () => {
    document.getElementById("userFormMessage").hidden = true;
    populateUserScopeSelect();
    openModal("userModal");
  });
  document.getElementById("logoutButton").addEventListener("click", () => window.location.reload());
  document.getElementById("userScopeType").addEventListener("change", populateUserScopeSelect);
  document.querySelector("#userForm [name='role']").addEventListener("change", event => {
    document.getElementById("userScopeType").value = event.target.value === "admin" ? "national" : "site";
    populateUserScopeSelect();
  });
  document.getElementById("siloForm").addEventListener("submit", submitSilo);
  document.getElementById("siloForm").addEventListener("input", updateSiloCalculation);
  document.querySelectorAll("[data-close]").forEach(button => {
    button.addEventListener("click", () => closeModal(button.dataset.close));
  });
  document.getElementById("closeReport").addEventListener("click", closeReport);
  document.getElementById("printReport").addEventListener("click", () => window.print());
  map.on("click", handleMapClick);
}

function renderAll() {
  updateFilters();
  renderMetrics();
  renderMap();
  renderSiteList();
  renderDependencyList();
  renderDetail();
  renderDashboard();
  renderAlerts();
  renderUsers();
  populateUserScopeSelect();
}

function setView(view) {
  if (view === "users" && state.currentUser?.role !== "admin") return;
  state.view = view;
  const shell = document.getElementById("appShell");
  shell.classList.remove("dashboard", "map", "sites", "alerts", "users");
  shell.classList.add(view === "sites" ? "map" : view);
  document.querySelectorAll(".nav-button").forEach(button => button.classList.toggle("active", button.dataset.view === view));
  renderAll();
  if (view === "map" || view === "sites") setTimeout(() => map.invalidateSize(), 50);
}

window.setModuleView = setView;

function applyRoleVisibility() {
  document.querySelectorAll(".admin-only").forEach(el => {
    el.hidden = state.currentUser?.role !== "admin";
  });
}

function updateFilters() {
  fillSelect("provinceFilter", ["Todas", ...unique(state.sites.map(s => s.province))], state.province);
  const provinceItems = state.province === "Todas" ? [...state.sites, ...state.dependencies] : [...state.sites, ...state.dependencies].filter(s => s.province === state.province);
  fillSelect("departmentFilter", ["Todos", ...unique(provinceItems.map(s => s.department).filter(Boolean))], state.department);
  fillSelect("siteTypeFilter", ["Todos", "CCP", "Sub-Centro", "Oficina Comercial", "Representante", "Otro Centro", "Sitio AFA"], state.siteType);
  fillSelect("ccpFilter", ["Todos", ...unique([
    ...state.sites.map(s => s.name.replace("CCP ", "")),
    ...state.dependencies.map(dep => dep.ccpAssociated).filter(Boolean)
  ])], state.ccp);
  fillSelect("grainFilter", ["Todos", ...unique(state.sites.flatMap(s => s.silos.map(silo => silo.grain)))], state.grain);
  fillSelect("riskFilter", ["Todos", ...riskOrder], state.risk);
  const sites = filteredSitesForSelector();
  if (!sites.some(site => site.id === state.selectedSiteId)) {
    state.selectedSiteId = sites[0]?.id || state.sites[0]?.id || null;
    state.selectedSiloId = sites[0]?.silos[0]?.id || null;
  }
  fillSelect("siteSelect", sites.map(site => site.id), state.selectedSiteId);
  const siteSelect = document.getElementById("siteSelect");
  siteSelect.querySelectorAll("option").forEach(option => {
    const site = state.sites.find(item => item.id === option.value);
    if (site) option.textContent = `${site.name} - ${site.town}, ${site.province}`;
  });
}

function fillSelect(id, values, selected) {
  document.getElementById(id).innerHTML = values
    .map(value => `<option value="${value}" ${value === selected ? "selected" : ""}>${display(value)}</option>`)
    .join("");
}

function unique(values) {
  return [...new Set(values)].sort((a, b) => display(a).localeCompare(display(b)));
}

function display(value) {
  const map = {
    Maiz: "Maiz",
    Cordoba: "Cordoba",
    Critico: "Critico",
    Atencion: "Atencion",
    Constitucion: "Constitucion"
  };
  return map[value] || riskLabels[value] || value;
}

function filteredSites() {
  const search = state.search.toLowerCase();
  const siloFilterActive = state.grain !== "Todos" || state.risk !== "Todos";
  return state.sites.filter(site => {
    const visibleSilos = site.silos.filter(matchesSilo);
    const haystack = `${site.name} ${site.town} ${site.department} ${site.province} ${site.silos.map(s => `${s.code} ${s.grain}`).join(" ")}`.toLowerCase();
    const ccpName = site.name.replace("CCP ", "");
    return (state.siteType === "Todos" || state.siteType === "CCP" || state.siteType === "Sitio AFA")
      && (state.ccp === "Todos" || ccpName === state.ccp || site.name === state.ccp)
      && (state.province === "Todas" || site.province === state.province)
      && (state.department === "Todos" || site.department === state.department)
      && (!search || haystack.includes(search))
      && (!siloFilterActive || visibleSilos.length > 0);
  });
}

function filteredSitesForSelector() {
  const search = state.search.toLowerCase();
  const sites = state.sites.filter(site => {
    const ccpName = site.name.replace("CCP ", "");
    const haystack = `${site.name} ${site.town} ${site.department} ${site.province}`.toLowerCase();
    return (state.ccp === "Todos" || ccpName === state.ccp || site.name === state.ccp)
      && (state.province === "Todas" || site.province === state.province)
      && (state.department === "Todos" || site.department === state.department)
      && (!search || haystack.includes(search));
  });
  return sites.length ? sites : state.sites;
}

function filteredDependencies() {
  const search = state.search.toLowerCase();
  return state.dependencies.filter(dep => {
    const haystack = `${dep.siteType} ${dep.province} ${dep.department || ""} ${dep.town} ${dep.ccpAssociated || ""} ${dep.publishedAddress || ""}`.toLowerCase();
    return (state.siteType === "Todos" || dep.siteType === state.siteType)
      && (state.ccp === "Todos" || dep.ccpAssociated === state.ccp)
      && (state.province === "Todas" || dep.province === state.province)
      && (state.department === "Todos" || dep.department === state.department)
      && (!search || haystack.includes(search));
  });
}

function matchesSilo(silo) {
  return (state.grain === "Todos" || silo.grain === state.grain)
    && (state.risk === "Todos" || silo.status === state.risk);
}

function aggregate(site) {
  const silos = site.silos.filter(matchesSilo);
  const worst = silos.reduce((acc, silo) => riskOrder.indexOf(silo.status) > riskOrder.indexOf(acc) ? silo.status : acc, "Normal");
  return {
    silos,
    worst,
    tons: silos.reduce((sum, silo) => sum + silo.tons, 0),
    volume: silos.reduce((sum, silo) => sum + silo.volume, 0),
    active: silos.filter(silo => silo.motorOn).length,
    alerts: silos.filter(silo => ["Riesgo", "Critico"].includes(silo.status)).length
  };
}

function renderMetrics() {
  const sites = filteredSites();
  const silos = sites.flatMap(site => site.silos.filter(matchesSilo));
  const tons = silos.reduce((sum, silo) => sum + silo.tons, 0);
  const volume = silos.reduce((sum, silo) => sum + silo.volume, 0);
  const critical = silos.filter(silo => silo.status === "Critico").length;
  const extHumidity = sites.length ? average(sites.map(s => s.weather.externalHumidity)).toFixed(1) : "0.0";
  document.getElementById("topMetrics").innerHTML = [
    [`${sites.length}`, "acopios visibles"],
    [`${silos.length}`, "silos monitoreados"],
    [`${tons.toLocaleString("es-AR")} t`, "stock estimado"],
    [`${volume.toLocaleString("es-AR")} m³`, "volumen grano"],
    [`${extHumidity}%`, "humedad externa"]
  ].map(([value, label]) => `<div class="metric"><strong>${value}</strong><span>${label}</span></div>`).join("");
}

function renderMap() {
  siteLayer.clearLayers();
  plantLayer.clearLayers();
  siloLayer.clearLayers();
  const sites = filteredSites();
  const bounds = [];
  sites.forEach(site => {
    const agg = aggregate(site);
    const siteMarker = L.circleMarker([site.lat, site.lng], {
      radius: 13,
      color: "#f4f542",
      weight: 3,
      fillColor: riskColors[agg.worst],
      fillOpacity: .96
    }).addTo(siteLayer);
    siteMarker.bindPopup(`<div class="popup-title">${site.name}</div><div>${site.town}, ${site.province}</div><div>${agg.silos.length} silos · ${agg.tons.toLocaleString("es-AR")} t</div><div>Clima: ${site.weather.externalHumidity}% HR ext.</div>`);
    siteMarker.bindTooltip(site.name, { direction: "top", offset: [0, -12], opacity: .92 });
    siteMarker.on("click", () => selectSite(site.id));
    bounds.push([site.lat, site.lng]);
    if (state.locatingSiteId === site.id) {
      L.marker([site.lat, site.lng], { draggable: true })
        .addTo(siteLayer)
        .bindTooltip("Arrastra para corregir ubicacion", { direction: "right" })
        .on("dragend", event => {
          const point = event.target.getLatLng();
          setPendingLocation(point.lat, point.lng);
        });
    }

    const layout = plantLayout(site);
    const boundary = state.drawingBoundarySiteId === site.id && state.boundaryDraft.length
      ? state.boundaryDraft.map(point => [point.lat, point.lng])
      : site.boundary?.length ? site.boundary.map(point => [point.lat, point.lng]) : null;
    if (boundary && (state.selectedSiteId === site.id || map.getZoom() >= 12)) {
      L.polygon(boundary, {
        color: "#39ff88",
        weight: 2,
        opacity: .95,
        fillColor: "#39ff88",
        fillOpacity: .08,
        dashArray: "7 6"
      }).addTo(plantLayer).bindPopup(`<div class="popup-title">Establecimiento</div><div>${site.name}</div>`);
    }
    if (state.selectedSiteId === site.id || map.getZoom() >= 12) {
      layout.silos.filter(item => matchesSilo(item.silo)).forEach(item => {
        const silo = item.silo;
        const marker = L.circle([item.lat, item.lng], {
        radius: Math.max(5, Number(silo.diameter || 18) / 2),
        color: "#f4fff7",
        weight: 2,
        fillColor: riskColors[silo.status],
        fillOpacity: .98
      }).addTo(siloLayer);
        marker.bindPopup(`<div class="popup-title">${silo.code}</div><div>${display(silo.grain)} · ${display(silo.status)}</div><div>Diam. ${silo.diameter || 18} m · Alt. ${silo.height || 18} m</div><div>Hum int. ${silo.internalHumidity}% · Hum grano ${silo.humidity}%</div>`);
        marker.on("click", () => selectSilo(site.id, silo.id));
        bounds.push([item.lat, item.lng]);
      });
    }
  });
  filteredDependencies().forEach(dep => {
    if (dep.lat == null || dep.lng == null) return;
    const marker = L.circleMarker([dep.lat, dep.lng], {
      radius: 9,
      color: "#56dcff",
      weight: 2,
      fillColor: "#063817",
      fillOpacity: .90
    }).addTo(siteLayer);
    marker.bindPopup(`<div class="popup-title">${dep.town}</div><div>${dep.siteType} · CCP ${dep.ccpAssociated}</div><div>${dep.province}${dep.department ? ` · ${dep.department}` : ""}</div><div>${dep.siloCount || 0} silos · ${(dep.capacityM3 || 0).toLocaleString("es-AR")} m³</div>`);
    marker.on("click", () => {
      const site = state.sites.find(item => item.id === dep.parentSiteId)
        || state.sites.find(item => item.town === dep.town && item.province === dep.province);
      if (site) selectSite(site.id);
    });
    bounds.push([dep.lat, dep.lng]);
  });
  const selected = state.sites.find(site => site.id === state.selectedSiteId) || sites[0];
  if (selected) {
    map.setView([selected.lat, selected.lng], 17, { animate: false });
  } else if (bounds.length) {
    map.fitBounds(bounds, { padding: [36, 36], maxZoom: 10 });
  }
}

function plantLayout(site) {
  const sorted = [...site.silos].sort((a, b) => a.code.localeCompare(b.code));
  const heading = ((hashCode(site.id) % 70) - 35) * Math.PI / 180;
  const spacing = 38;
  const rowGap = 42;
  const perRow = Math.max(3, Math.ceil(Math.sqrt(sorted.length + 2)));
  const centerIndex = (perRow - 1) / 2;
  const rows = Math.ceil(sorted.length / perRow);
  const centerRow = (rows - 1) / 2;
  const silos = sorted.map((silo, index) => {
    const row = Math.floor(index / perRow);
    const col = index % perRow;
    const x = (col - centerIndex) * spacing;
    const y = (row - centerRow) * rowGap;
    const rotatedX = x * Math.cos(heading) - y * Math.sin(heading);
    const rotatedY = x * Math.sin(heading) + y * Math.cos(heading);
    const point = offsetLatLng(site.lat, site.lng, rotatedX, rotatedY);
    return { silo, lat: point.lat, lng: point.lng, x: rotatedX, y: rotatedY };
  });
  const margin = 50;
  const xs = silos.map(item => item.x);
  const ys = silos.map(item => item.y);
  const minX = Math.min(...xs, -70) - margin;
  const maxX = Math.max(...xs, 70) + margin;
  const minY = Math.min(...ys, -70) - margin;
  const maxY = Math.max(...ys, 70) + margin;
  const corners = [
    [minX, minY],
    [maxX, minY],
    [maxX + 24, maxY],
    [minX - 24, maxY]
  ].map(([x, y]) => {
    const rotatedX = x * Math.cos(heading) - y * Math.sin(heading);
    const rotatedY = x * Math.sin(heading) + y * Math.cos(heading);
    const point = offsetLatLng(site.lat, site.lng, rotatedX, rotatedY);
    return [point.lat, point.lng];
  });
  return { silos, boundary: corners };
}

function offsetLatLng(lat, lng, eastMeters, northMeters) {
  return {
    lat: lat + (northMeters / 111320),
    lng: lng + (eastMeters / (111320 * Math.cos(lat * Math.PI / 180)))
  };
}

function hashCode(text) {
  return [...text].reduce((hash, char) => ((hash << 5) - hash) + char.charCodeAt(0), 0);
}

function renderSiteList() {
  const list = document.getElementById("siteList");
  list.innerHTML = filteredSites().map(site => {
    const agg = aggregate(site);
    return `
      <article class="site-card ${state.selectedSiteId === site.id ? "active" : ""}" data-site="${site.id}">
        <div class="site-head">
          <div>
            <div class="site-name">${site.name}</div>
            <div class="site-meta">${site.town} · ${site.department} · ${site.province}</div>
            <div class="site-meta">${site.region || "RED AFA"}${site.address ? ` · ${site.address}` : ""}</div>
          </div>
          <span class="chip ${riskClass(agg.worst)}">${display(agg.worst)}</span>
        </div>
        <div class="site-meta">${site.phone ? `Tel ${site.phone}` : "Tel s/d"} · ${site.email || "correo s/d"}</div>
        ${site.mapsUrl ? `<a class="map-link" href="${site.mapsUrl}" target="_blank" rel="noopener">Abrir ubicacion exacta en Maps</a>` : ""}
        <div class="site-stats">
          <div class="mini"><strong>${agg.silos.length}</strong><span>silos</span></div>
          <div class="mini"><strong>${agg.tons.toLocaleString("es-AR")} t</strong><span>stock</span></div>
          <div class="mini"><strong>${site.weather.externalHumidity}%</strong><span>HR externa</span></div>
        </div>
      </article>`;
  }).join("");
  list.querySelectorAll("[data-site]").forEach(card => card.addEventListener("click", () => selectSite(card.dataset.site)));
}

function renderDependencyList() {
  const list = document.getElementById("dependencyList");
  const dependencies = filteredDependencies();
  list.innerHTML = dependencies.slice(0, 80).map(dep => `
    <article class="dependency-card">
      <div class="site-head">
        <div>
          <div class="site-name">${dep.town}</div>
          <div class="site-meta">${dep.siteType} · ${dep.province}${dep.department ? ` · ${dep.department}` : ""}</div>
        </div>
        <span class="chip normal">${dep.ccpAssociated}</span>
      </div>
      <div class="site-meta">${dep.publishedAddress || "Sin direccion cargada"} · ${dep.locationSource}</div>
      <div class="site-stats">
        <div class="mini"><strong>${dep.siloCount || 0}</strong><span>silos</span></div>
        <div class="mini"><strong>${(dep.capacityM3 || 0).toLocaleString("es-AR")} m³</strong><span>capacidad</span></div>
        <div class="mini"><strong>${dep.lat == null ? "No" : "Si"}</strong><span>coord.</span></div>
      </div>
    </article>
  `).join("") || `<div class="note">No hay dependencias para estos filtros.</div>`;
}

function allVisibleSilos() {
  return state.sites.flatMap(site => site.silos.map(silo => ({ ...silo, site })));
}

function renderDashboard() {
  const silos = allVisibleSilos();
  const totalCapacity = silos.reduce((sum, silo) => sum + Number(silo.capacity || 0), 0);
  const totalVolume = silos.reduce((sum, silo) => sum + Number(silo.volume || 0), 0);
  const totalTons = silos.reduce((sum, silo) => sum + Number(silo.tons || 0), 0);
  const alerts = silos.filter(silo => ["Riesgo", "Critico"].includes(silo.status));
  const avgExternalHumidity = state.sites.length ? average(state.sites.map(site => site.weather.externalHumidity)).toFixed(1) : "0.0";
  document.getElementById("dashboardView").innerHTML = `
    <div class="section-head">
      <div>
        <p class="section-title">Resumen operativo</p>
        <h2>${state.currentUser?.role === "admin" ? "Vista nacional / administracion" : state.currentUser?.name}</h2>
      </div>
      <span class="chip normal">${state.currentUser?.role === "admin" ? "Admin" : "CCP"}</span>
    </div>
    <div class="dashboard-grid">
      ${dashboardCard(state.sites.length, "establecimientos visibles")}
      ${dashboardCard(silos.length, "silos monitoreados")}
      ${dashboardCard(`${totalCapacity.toLocaleString("es-AR")} m³`, "capacidad total")}
      ${dashboardCard(`${totalVolume.toLocaleString("es-AR")} m³`, "volumen ocupado")}
      ${dashboardCard(`${totalTons.toLocaleString("es-AR")} t`, "stock estimado")}
      ${dashboardCard(alerts.length, "alertas riesgo/critico")}
      ${dashboardCard(`${avgExternalHumidity}%`, "humedad externa prom.")}
      ${dashboardCard(state.dependencies.length, "dependencias cargadas")}
    </div>
    <div class="dashboard-sections">
      <div class="dashboard-card">
        <p class="section-title">Acciones sugeridas</p>
        <div class="site-meta">Revisar silos criticos, validar coordenadas de plantas con fuente Centro localidad y completar dependencias sin capacidad/silos cargados.</div>
      </div>
      <div class="dashboard-card">
        <p class="section-title">Alertas recientes</p>
        ${alerts.slice(0, 6).map(silo => `<div class="site-meta">${silo.site.name} · ${silo.code} · ${display(silo.status)} · humedad ${silo.humidity}%</div>`).join("") || `<div class="site-meta">Sin alertas activas para esta vista.</div>`}
      </div>
    </div>`;
}

function dashboardCard(value, label) {
  return `<div class="dashboard-card"><strong>${value}</strong><span>${label}</span></div>`;
}

function renderAlerts() {
  const alerts = allVisibleSilos().filter(silo => ["Riesgo", "Critico", "Atencion"].includes(silo.status));
  document.getElementById("alertsView").innerHTML = `
    <div class="section-head">
      <div>
        <p class="section-title">Monitoreo</p>
        <h2>Alertas por conservacion</h2>
      </div>
      <span class="chip ${alerts.some(a => a.status === "Critico") ? "critico" : "normal"}">${alerts.length} activas</span>
    </div>
    <div class="alert-list">
      ${alerts.map(silo => `
        <article class="alert-card">
          <div class="row">
            <div>
              <strong>${silo.site.name} · ${silo.code}</strong>
              <div class="site-meta">${display(silo.grain)} · humedad grano ${silo.humidity}% · temp ${silo.temp}°C · ${silo.safeDays} dias seguros</div>
            </div>
            <span class="chip ${riskClass(silo.status)}">${display(silo.status)}</span>
          </div>
        </article>`).join("") || `<div class="note">No hay alertas en esta vista.</div>`}
    </div>`;
}

async function loadUsers() {
  if (state.currentUser?.role !== "admin") {
    state.users = [];
    return;
  }
  const response = await fetch("/api/users");
  const payload = await response.json();
  state.users = payload.users;
}

function renderUsers() {
  if (state.currentUser?.role !== "admin") return;
  document.getElementById("userList").innerHTML = state.users.map(user => {
    const site = state.sites.find(item => item.id === user.scopeValue || item.id === user.siteId);
    const scopeLabel = user.scopeType === "national"
      ? "Toda la red nacional"
      : user.scopeType === "province"
        ? `Provincia ${user.scopeValue}`
        : site ? site.name : user.scopeValue || "Sin alcance";
    return `
      <article class="user-card">
        <div class="row">
          <div>
            <strong>${user.name}</strong>
            <div class="site-meta">${user.email} - ${user.role === "admin" ? "Admin" : "Operador"} - ${scopeLabel}</div>
            <div class="site-meta">${user.email} · ${user.role === "admin" ? "Admin nacional" : "Operador CCP"}${site ? ` · ${site.name}` : ""}</div>
          </div>
          <span class="chip ${user.active ? "normal" : "riesgo"}">${user.active ? "Activo" : "Inactivo"}</span>
        </div>
      </article>`;
  }).join("");
}

function populateUserScopeSelect() {
  const select = document.getElementById("userScopeValue");
  if (!select) return;
  const scopeType = document.getElementById("userScopeType")?.value || "site";
  if (scopeType === "national") {
    select.innerHTML = `<option value="">Toda la red AFA</option>`;
    select.disabled = true;
    return;
  }
  select.disabled = false;
  if (scopeType === "province") {
    select.innerHTML = unique(state.sites.map(site => site.province))
      .map(province => `<option value="${province}">${province}</option>`)
      .join("");
    return;
  }
  select.innerHTML = state.sites
    .map(site => `<option value="${site.id}">${site.name} - ${site.town}, ${site.province}</option>`)
    .join("");
}

function renderPlantFocus() {
  const el = document.getElementById("plantFocus");
  const site = state.sites.find(item => item.id === state.selectedSiteId) || filteredSites()[0] || state.sites[0];
  if (!site) {
    el.innerHTML = "";
    return;
  }
  const agg = aggregate(site);
  const dependencies = state.dependencies.filter(dep => dep.ccpAssociated === site.name.replace("CCP ", ""));
  const capacity = site.silos.reduce((sum, silo) => sum + Number(silo.capacity || 0), 0);
  el.innerHTML = `
    <div class="row">
      <div>
        <h2>${site.name}</h2>
        <div class="site-meta">${site.town} · ${site.department} · ${site.province}</div>
        <div class="site-meta">${site.locationSource || "Centro localidad"} · ${dependencies.length} dependencias asociadas</div>
      </div>
      <span class="chip ${riskClass(agg.worst)}">${display(agg.worst)}</span>
    </div>
    <div class="focus-kpis">
      <div class="mini"><strong>${site.silos.length}</strong><span>silos</span></div>
      <div class="mini"><strong>${capacity.toLocaleString("es-AR")} m³</strong><span>capacidad</span></div>
      <div class="mini"><strong>${agg.volume.toLocaleString("es-AR")} m³</strong><span>volumen</span></div>
      <div class="mini"><strong>${site.weather.externalHumidity}%</strong><span>HR ext.</span></div>
    </div>
    <div class="focus-actions">
      <button class="button" id="focusAddSilo">Agregar silo</button>
      <button class="button secondary" id="focusLocate">Ubicar planta</button>
      <button class="button secondary" id="focusReport">Informe</button>
    </div>
  `;
  document.getElementById("focusAddSilo").addEventListener("click", () => openSiloForm(site));
  document.getElementById("focusLocate").addEventListener("click", () => startLocatePlant(site));
  document.getElementById("focusReport").addEventListener("click", () => {
    const silo = site.silos.find(item => item.id === state.selectedSiloId) || site.silos[0];
    showReport(site, silo);
  });
}

function renderDetail() {
  const sites = filteredSites();
  const site = sites.find(item => item.id === state.selectedSiteId) || sites[0] || state.sites[0];
  if (!site) return;
  state.selectedSiteId = site.id;
  const silos = site.silos.filter(matchesSilo);
  const silo = silos.find(item => item.id === state.selectedSiloId) || silos[0] || site.silos[0];
  state.selectedSiloId = silo?.id || null;
  const agg = aggregate(site);
  if (!silo) {
    document.getElementById("detail").innerHTML = `
      <div class="detail-hero">
        <div class="row">
          <div>
            <h2>${site.name}</h2>
            <div class="site-meta">Ubicacion: ${site.locationSource || "Base oficial AFA"}${site.plantNumber ? ` · CP/Planta ${site.plantNumber}` : ""}${site.address ? ` · ${site.address}` : ""}</div>
            <div class="site-meta">${site.town} · ${site.department} · ${site.province}</div>
            <div class="site-meta">${site.region || "RED AFA"} · ${site.phone || "tel s/d"} · ${site.email || "correo s/d"}</div>
          </div>
          <span class="chip normal">Sin silos</span>
        </div>
      </div>
      ${siteInfoPanel(site)}
      ${weatherPanel(site)}
      ${plantSummary(site, agg)}
      <p class="section-title">Silos del establecimiento</p>
      <div class="map-tools">
        <button class="button" id="addSilo">Agregar primer silo</button>
        <button class="button secondary" id="drawSilo">Dibujar silo</button>
        <button class="button secondary" id="locatePlant">Mover punto</button>
        ${state.locatingSiteId === site.id ? `<button class="button" id="saveLocation">Guardar ubicacion</button>` : ""}
        <button class="button secondary" id="editCoords">Coordenadas</button>
        <button class="button secondary" id="editSite">Editar ficha</button>
        <button class="button secondary" id="drawBoundary">${state.drawingBoundarySiteId === site.id ? "Guardar limite" : "Dibujar limite"}</button>
      </div>
      <div class="note">${mapModeHelp(site) || "Sitio cargado desde la base oficial AFA. Falta relevar silos fisicos: centro del silo, diametro, altura, grano, humedad y sensores internos."}</div>
      <div class="detail-grid">
        ${valueCard("Estado de carga", "Pendiente", "Sin silos cargados todavia")}
        ${valueCard("Coordenadas", `${Number(site.lat).toFixed(7)}, ${Number(site.lng).toFixed(7)}`, site.coordMaps || site.locationSource || "Base oficial")}
        ${valueCard("Capacidad", "0 m³", "Se calcula automaticamente al cargar diametro y altura")}
      </div>
      <div class="note">${sourceNote}</div>
    `;
    document.getElementById("addSilo").addEventListener("click", () => openSiloForm(site));
    document.getElementById("drawSilo").addEventListener("click", () => startDrawSilo(site));
    document.getElementById("locatePlant").addEventListener("click", () => startLocatePlant(site));
    document.getElementById("saveLocation")?.addEventListener("click", () => savePendingLocation(site));
    document.getElementById("editCoords").addEventListener("click", () => promptCoordinates(site));
    document.getElementById("editSite").addEventListener("click", () => promptSiteMetadata(site));
    document.getElementById("drawBoundary").addEventListener("click", () => toggleBoundary(site));
    return;
  }
  document.getElementById("detail").innerHTML = `
    <div class="detail-hero">
      <div class="row">
        <div>
          <h2>${site.name}</h2>
          <div class="site-meta">Ubicacion: ${site.locationSource || "Centro localidad"}${site.plantNumber ? ` · CP/Planta ${site.plantNumber}` : ""}${site.cuit ? ` · CUIT ${site.cuit}` : ""}</div>
          <div class="site-meta">${site.town} · ${site.department} · ${site.province}</div>
          <div class="site-meta">${site.region || "RED AFA"} · ${site.address || "direccion s/d"}</div>
        </div>
        <span class="chip ${riskClass(agg.worst)}">${display(agg.worst)}</span>
      </div>
    </div>

    ${siteInfoPanel(site)}

    ${weatherPanel(site)}

    ${plantSummary(site, agg)}

    <p class="section-title">Silos del acopio</p>
    <div class="map-tools">
      <button class="button" id="addSilo">Agregar silo</button>
      <button class="button secondary" id="drawSilo">Dibujar silo</button>
      <button class="button secondary" id="locatePlant">Mover punto</button>
      ${state.locatingSiteId === site.id ? `<button class="button" id="saveLocation">Guardar ubicacion</button>` : ""}
      <button class="button secondary" id="editCoords">Coordenadas</button>
      <button class="button secondary" id="editSite">Editar ficha</button>
      <button class="button secondary" id="drawBoundary">${state.drawingBoundarySiteId === site.id ? "Guardar limite" : "Dibujar limite"}</button>
    </div>
    <div class="silo-layout-note">${mapModeHelp(site) || locationHelp(site)}</div>
    <div class="silo-list">
      ${silos.map(item => `
        <div class="silo-row ${item.id === silo.id ? "active" : ""}" data-silo="${item.id}">
          <div>
            <strong>${item.code}</strong>
            <small>${display(item.grain)} · diam. ${item.diameter || 18} m · ${item.fill}% ocupado · ${item.safeDays} dias seguros</small>
          </div>
          <span class="chip ${riskClass(item.status)}">${display(item.status)}</span>
        </div>`).join("")}
    </div>

    ${storagePanel(silo)}

    <div class="detail-grid">
      ${valueCard("Humedad del grano", `${silo.humidity}%`, `Limite ${grainLimits[silo.grain]}%`)}
      ${valueCard("Humedad interna", `${silo.internalHumidity}%`, `Externa ${site.weather.externalHumidity}% · rocio ${site.weather.dewPoint}°C`)}
      ${valueCard("Temperatura grano", `${silo.temp}°C`, `Interna ${silo.internalTemp}°C · externa ${site.weather.externalTemperature}°C`)}
      ${valueCard("Volumen ocupado", `${silo.volume.toLocaleString("es-AR")} m³`, `${silo.fill}% de ${silo.capacity.toLocaleString("es-AR")} m³`)}
      ${valueCard("Geometria silo", `${silo.diameter || 18} m x ${silo.height || 18} m`, "Capacidad calculada por cilindro")}
      ${valueCard("Aireacion", silo.motorOn ? "Encendida" : "Apagada", `${display(silo.mode)} · regla automatizable`)}
      ${valueCard("Trazabilidad", silo.producer, `Ingreso ${formatDate(silo.loadedAt)}`)}
    </div>

    <div class="button-row">
      <button class="button" id="toggleMotor">${silo.motorOn ? "Apagar aireador" : "Encender aireador"}</button>
      <button class="button secondary" id="makeReport">Generar informe</button>
    </div>

    <p class="section-title">Eventos recientes</p>
    <div class="timeline">${eventsFor(site, silo).map(event => `<div class="event"><strong>${event.title}</strong>${event.text}</div>`).join("")}</div>
    <div class="note">${sourceNote}</div>
  `;
  document.querySelectorAll("[data-silo]").forEach(row => row.addEventListener("click", () => selectSilo(site.id, row.dataset.silo)));
  document.getElementById("addSilo").addEventListener("click", () => openSiloForm(site));
  document.getElementById("drawSilo").addEventListener("click", () => startDrawSilo(site));
  document.getElementById("locatePlant").addEventListener("click", () => startLocatePlant(site));
  document.getElementById("saveLocation")?.addEventListener("click", () => savePendingLocation(site));
  document.getElementById("editCoords").addEventListener("click", () => promptCoordinates(site));
  document.getElementById("editSite").addEventListener("click", () => promptSiteMetadata(site));
  document.getElementById("drawBoundary").addEventListener("click", () => toggleBoundary(site));
  document.getElementById("toggleMotor").addEventListener("click", () => {
    silo.motorOn = !silo.motorOn;
    renderAll();
  });
  document.getElementById("makeReport").addEventListener("click", () => showReport(site, silo));
}

function weatherPanel(site) {
  const weather = site.weather;
  return `
    <div class="weather-card">
      <p class="section-title">Clima externo del acopio</p>
      <div class="row">
        <div>
          <div class="weather-value">${weather.externalHumidity}% HR</div>
          <div class="site-meta">Humedad externa crítica para decidir aireacion</div>
        </div>
        <span class="chip normal">${weather.source || "Demo clima"}</span>
      </div>
      <div class="weather-grid">
        <div class="mini"><strong>${weather.externalTemperature}°C</strong><span>temp. externa</span></div>
        <div class="mini"><strong>${weather.dewPoint}°C</strong><span>punto de rocio</span></div>
        <div class="mini"><strong>${weather.windKmh} km/h</strong><span>viento</span></div>
        <div class="mini"><strong>${weather.pressureHpa}</strong><span>hPa</span></div>
        <div class="mini"><strong>${weather.rainMm} mm</strong><span>lluvia</span></div>
        <div class="mini"><strong>${formatShortTime(weather.recordedAt)}</strong><span>ultima lectura</span></div>
      </div>
    </div>`;
}

function siteInfoPanel(site) {
  return `
    <div class="weather-card">
      <p class="section-title">Ficha del sitio AFA</p>
      <div class="detail-grid compact">
        ${valueCard("Region", site.region || "s/d", site.sourceFile || site.registryStatus || "Fuente AFA")}
        ${valueCard("Domicilio", site.address || "s/d", `${site.town}, ${site.province}`)}
        ${valueCard("Contacto", site.phone || "s/d", site.email || "correo s/d")}
        ${valueCard("Coordenada Maps", site.coordMaps || `${Number(site.lat).toFixed(7)},${Number(site.lng).toFixed(7)}`, `${site.originalLat || ""} ${site.originalLng || ""}`.trim() || "decimal")}
      </div>
      <div class="button-row">
        ${site.mapsUrl ? `<a class="button" href="${site.mapsUrl}" target="_blank" rel="noopener">Abrir en Maps</a>` : ""}
        ${site.directionsUrl ? `<a class="button secondary" href="${site.directionsUrl}" target="_blank" rel="noopener">Como llegar</a>` : ""}
      </div>
    </div>`;
}

function plantSummary(site, agg) {
  const avgDiameter = average(site.silos.map(silo => Number(silo.diameter || 18))).toFixed(1);
  const capacity = site.silos.reduce((sum, silo) => sum + Number(silo.capacity || 0), 0);
  return `
    <div class="plant-summary">
      <div class="mini"><strong>${site.silos.length}</strong><span>silos cargados</span></div>
      <div class="mini"><strong>${capacity.toLocaleString("es-AR")} m³</strong><span>capacidad total</span></div>
      <div class="mini"><strong>${agg.volume.toLocaleString("es-AR")} m³</strong><span>volumen actual</span></div>
      <div class="mini"><strong>${avgDiameter} m</strong><span>diametro prom.</span></div>
    </div>`;
}

function locationHelp(site) {
  const source = (site.locationSource || "").toLowerCase();
  if (state.locatingSiteId === site.id) {
    return "Modo ubicacion activo: hace click o arrastra el punto hasta el lugar real. Luego pulsa Guardar ubicacion.";
  }
  if (source.includes("centro")) {
    return "Esta planta todavia usa coordenada aproximada de localidad. Pulsa Ajustar ubicacion, busca el acopio en satelite y hace click sobre el centro real de la planta.";
  }
  return "Cada circunferencia representa el diametro real del silo. Para relevar la planta se ajusta centro, limite del acopio, diametro y altura de cada silo.";
}

function mapModeHelp(site) {
  if (state.drawingSiloSiteId === site.id) {
    return "Modo dibujo de silo activo: hace click sobre el centro real del silo en la imagen satelital. Luego carga diametro y altura para calcular volumen.";
  }
  if (state.drawingBoundarySiteId === site.id) {
    return `Modo limite activo: hace clicks sobre los vertices del predio. Puntos marcados: ${state.boundaryDraft.length}. Pulsa Guardar limite al terminar.`;
  }
  return "";
}

function storagePanel(silo) {
  const safePct = Math.max(0, Math.min(100, Math.round((silo.safeDays / 150) * 100)));
  const fillPct = Math.max(3, Math.min(100, silo.fill));
  return `
    <div class="storage-panel">
      <div class="storage-top">
        <div class="silo-visual" aria-label="Nivel del silo">
          <div class="silo-fill" style="height:${fillPct}%"></div>
        </div>
        <div>
          <p class="section-title">Volumen y almacenaje seguro</p>
          <div class="row">
            <div>
              <div class="big-number">${silo.fill}% ocupado</div>
              <div class="site-meta">${silo.volume.toLocaleString("es-AR")} m³ de grano · ${silo.capacity.toLocaleString("es-AR")} m³ capacidad calculada</div>
            </div>
            <span class="chip ${riskClass(silo.status)}">${display(silo.status)}</span>
          </div>
          <div class="bar"><span style="width:${safePct}%"></span></div>
          <div class="site-meta">${silo.safeDays} dias seguros estimados antes de intervencion preventiva</div>
        </div>
      </div>
      <div class="storage-kpis">
        <div class="mini"><strong>${silo.tons.toLocaleString("es-AR")} t</strong><span>peso estimado</span></div>
        <div class="mini"><strong>${silo.diameter || 18} m</strong><span>diametro</span></div>
        <div class="mini"><strong>${silo.height || 18} m</strong><span>altura</span></div>
      </div>
    </div>`;
}

function valueCard(label, value, detail) {
  return `<div class="value-card"><span>${label}</span><strong>${value}</strong><div class="site-meta">${detail}</div></div>`;
}

function eventsFor(site, silo) {
  const limit = grainLimits[silo.grain];
  const events = [
    { title: "Ingreso de lote", text: `${formatDate(silo.loadedAt)} · ${display(silo.grain)} desde ${silo.origin}.` },
    { title: "Ultima lectura interna", text: `Hum grano ${silo.humidity}% · hum interna ${silo.internalHumidity}% · temp ${silo.temp}°C.` },
    { title: "Lectura externa", text: `HR externa ${site.weather.externalHumidity}% · punto de rocio ${site.weather.dewPoint}°C · lluvia ${site.weather.rainMm} mm.` }
  ];
  if (silo.humidity > limit) events.push({ title: "Regla de preservacion", text: `Humedad por encima de ${limit}%; aireacion condicionada por clima externo.` });
  if (silo.motorOn) events.push({ title: "Aireador activo", text: `${display(silo.mode)} · evento guardado para trazabilidad del certificado.` });
  if (silo.status === "Critico") events.push({ title: "Alerta critica", text: "Requiere inspeccion operativa, contraste de sensor y decision de aireacion." });
  return events;
}

function showReport(site, silo) {
  const report = `
CERTIFICADO DIGITAL DE CONSERVACION DE GRANOS

Acopio: ${site.name} - ${site.town}, ${site.province}
Silo: ${silo.code}
Grano: ${display(silo.grain)}
Campaña: ${silo.campaign}
Origen: ${silo.origin}
Productor / remitente: ${silo.producer}
Fecha de ingreso: ${formatDate(silo.loadedAt)}
Dias almacenados: ${daysBetween(silo.loadedAt)}

Humedad grano: ${silo.humidity}%
Temperatura grano: ${silo.temp}°C
Humedad interna: ${silo.internalHumidity}%
Temperatura interna: ${silo.internalTemp}°C
Humedad externa acopio: ${site.weather.externalHumidity}%
Temperatura externa acopio: ${site.weather.externalTemperature}°C
Punto de rocio externo: ${site.weather.dewPoint}°C

Volumen ocupado: ${silo.volume.toLocaleString("es-AR")} m³ de ${silo.capacity.toLocaleString("es-AR")} m³
Stock estimado: ${silo.tons.toLocaleString("es-AR")} t
Dias seguros estimados: ${silo.safeDays}
Estado de preservacion: ${display(silo.status)}
Aireacion: ${silo.motorOn ? "Encendida" : "Apagada"} (${display(silo.mode)})

Observacion: informe demo. En produccion debe firmarse con usuario, fecha, trazabilidad de sensores y QR de validacion.
  `.trim();
  document.getElementById("reportBody").textContent = report;
  document.getElementById("reportModal").classList.add("open");
  document.getElementById("reportModal").setAttribute("aria-hidden", "false");
}

function closeReport() {
  document.getElementById("reportModal").classList.remove("open");
  document.getElementById("reportModal").setAttribute("aria-hidden", "true");
}

function openModal(id) {
  document.getElementById(id).classList.add("open");
  document.getElementById(id).setAttribute("aria-hidden", "false");
}

function closeModal(id) {
  document.getElementById(id).classList.remove("open");
  document.getElementById(id).setAttribute("aria-hidden", "true");
}

function selectedSite() {
  return state.sites.find(site => site.id === state.selectedSiteId) || state.sites[0];
}

function openSiloForm(site, point = null) {
  const form = document.getElementById("siloForm");
  form.reset();
  form.elements.code.value = `S-${site.town.slice(0, 3).toUpperCase()}-${String(site.silos.length + 1).padStart(2, "0")}`;
  form.elements.lat.value = (point?.lat ?? site.lat + 0.00025).toFixed(6);
  form.elements.lng.value = (point?.lng ?? site.lng + 0.00025).toFixed(6);
  form.dataset.siteId = site.id;
  updateSiloCalculation();
  openModal("siloModal");
}

function formPayload(form) {
  return [...new FormData(form).entries()].reduce((payload, [key, value]) => {
    const input = form.elements[key];
    payload[key] = input && input.type === "number" ? Number(value) : value;
    return payload;
  }, {});
}

async function submitSite(event) {
  event.preventDefault();
  const payload = formPayload(event.currentTarget);
  const response = await fetch("/api/sites", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) throw new Error(await response.text());
  const result = await response.json();
  closeModal("siteModal");
  await refreshData(result.siteId);
}

async function submitDependency(event) {
  event.preventDefault();
  const payload = formPayload(event.currentTarget);
  payload.parent_site_id = findParentSiteId(payload.ccp_associated);
  if (!payload.lat) delete payload.lat;
  if (!payload.lng) delete payload.lng;
  const response = await fetch("/api/dependencies", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) throw new Error(await response.text());
  closeModal("dependencyModal");
  await refreshData();
}

async function submitUser(event) {
  event.preventDefault();
  const payload = formPayload(event.currentTarget);
  const message = document.getElementById("userFormMessage");
  message.hidden = true;
  if (payload.scope_type === "national") delete payload.scope_value;
  if (payload.scope_type === "site") payload.site_id = payload.scope_value;
  const response = await fetch("/api/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: "No se pudo crear el usuario" }));
    message.textContent = error.error || "No se pudo crear el usuario";
    message.hidden = false;
    return;
  }
  closeModal("userModal");
  event.currentTarget.reset();
  document.getElementById("userScopeType").value = "national";
  populateUserScopeSelect();
  await loadUsers();
  renderUsers();
}

function findParentSiteId(ccpName) {
  const normalized = ccpName.trim().toLowerCase();
  const site = state.sites.find(item => item.name.replace("CCP ", "").toLowerCase() === normalized || item.name.toLowerCase() === normalized);
  return site?.id || null;
}

async function submitSilo(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const siteId = form.dataset.siteId || state.selectedSiteId;
  const payload = formPayload(form);
  payload.internal_humidity = payload.internal_humidity || 58;
  payload.internal_temperature = payload.grain_temperature - 1;
  const response = await fetch(`/api/sites/${siteId}/silos`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) throw new Error(await response.text());
  const result = await response.json();
  closeModal("siloModal");
  await refreshData(siteId, result.siloId);
}

async function refreshData(siteId = state.selectedSiteId, siloId = state.selectedSiloId) {
  const response = await fetch("/api/sites");
  const payload = await response.json();
  const dependencyResponse = await fetch("/api/dependencies");
  const dependencyPayload = await dependencyResponse.json();
  applyAccess(payload.sites, dependencyPayload.dependencies);
  state.selectedSiteId = siteId;
  state.selectedSiloId = siloId;
  renderAll();
}

function startLocatePlant(site) {
  state.locatingSiteId = site.id;
  state.drawingSiloSiteId = null;
  state.drawingBoundarySiteId = null;
  pendingLocation = { lat: site.lat, lng: site.lng };
  map.setView([site.lat, site.lng], 16, { animate: true });
  if (pendingLocationMarker) {
    pendingLocationMarker.remove();
    pendingLocationMarker = null;
  }
  renderDetail();
}

function setPendingLocation(lat, lng) {
  pendingLocation = { lat, lng };
  if (pendingLocationMarker) pendingLocationMarker.remove();
  pendingLocationMarker = L.marker([lat, lng], { draggable: true })
    .addTo(map)
    .bindPopup("Ubicacion pendiente. Pulsa Guardar ubicacion.")
    .openPopup()
    .on("dragend", event => {
      const point = event.target.getLatLng();
      setPendingLocation(point.lat, point.lng);
    });
}

async function savePendingLocation(site) {
  if (!pendingLocation) {
    alert("Primero marca o arrastra el punto en el mapa.");
    return;
  }
  state.locatingSiteId = null;
  const point = pendingLocation;
  pendingLocation = null;
  if (pendingLocationMarker) {
    pendingLocationMarker.remove();
    pendingLocationMarker = null;
  }
  await updateSiteLocation(site.id, point.lat, point.lng, "Ubicacion corregida por usuario");
}

function startDrawSilo(site) {
  state.drawingSiloSiteId = site.id;
  state.locatingSiteId = null;
  state.drawingBoundarySiteId = null;
  map.setView([site.lat, site.lng], 18, { animate: true });
  renderDetail();
}

async function toggleBoundary(site) {
  if (state.drawingBoundarySiteId === site.id) {
    if (state.boundaryDraft.length < 3) {
      alert("Marca al menos 3 puntos para cerrar el limite.");
      return;
    }
    const response = await fetch(`/api/sites/${site.id}/boundary`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ boundary: state.boundaryDraft })
    });
    if (!response.ok) throw new Error(await response.text());
    state.drawingBoundarySiteId = null;
    state.boundaryDraft = [];
    await refreshData(site.id, state.selectedSiloId);
    return;
  }
  state.drawingBoundarySiteId = site.id;
  state.boundaryDraft = site.boundary ? [...site.boundary] : [];
  state.locatingSiteId = null;
  state.drawingSiloSiteId = null;
  map.setView([site.lat, site.lng], 18, { animate: true });
  renderAll();
}

async function handleMapClick(event) {
  if (state.drawingSiloSiteId) {
    const site = state.sites.find(item => item.id === state.drawingSiloSiteId);
    if (!site) return;
    state.drawingSiloSiteId = null;
    openSiloForm(site, event.latlng);
    renderDetail();
    return;
  }
  if (state.drawingBoundarySiteId) {
    state.boundaryDraft.push({ lat: event.latlng.lat, lng: event.latlng.lng });
    renderAll();
    return;
  }
  if (!state.locatingSiteId) return;
  const { lat, lng } = event.latlng;
  setPendingLocation(lat, lng);
  renderDetail();
}

async function promptCoordinates(site) {
  const text = prompt("Pega coordenadas o link de Maps", site.coordMaps || `${site.lat},${site.lng}`);
  if (text === null) return;
  const parsed = parseCoordinates(text);
  if (!parsed) {
    alert("Coordenadas invalidas. Ej: -34.06278,-60.10271 o 34°03'46\"S 60°06'09\"O");
    return;
  }
  await updateSiteLocation(site.id, parsed.lat, parsed.lng, "Coordenada editada manualmente");
}

function parseCoordinates(text) {
  const cleaned = String(text).trim();
  const decimal = cleaned.match(/(-?\d+(?:[.,]\d+)?)\s*[,;\s]\s*(-?\d+(?:[.,]\d+)?)/);
  if (decimal) {
    const lat = Number(decimal[1].replace(",", "."));
    const lng = Number(decimal[2].replace(",", "."));
    if (Number.isFinite(lat) && Number.isFinite(lng)) return normalizeLatLng(lat, lng, cleaned);
  }
  const parts = cleaned.toUpperCase().split(/[;,]|(?<=\b[SN])\s+/).filter(Boolean);
  if (parts.length >= 2) {
    const lat = parseDms(parts[0]);
    const lng = parseDms(parts.slice(1).join(" "));
    if (Number.isFinite(lat) && Number.isFinite(lng)) return { lat, lng };
  }
  return null;
}

function normalizeLatLng(lat, lng, source) {
  const upper = source.toUpperCase();
  if (upper.includes("S") && lat > 0) lat *= -1;
  if ((upper.includes("O") || upper.includes("W")) && lng > 0) lng *= -1;
  return { lat, lng };
}

function parseDms(value) {
  const upper = value.toUpperCase().replace(/,/g, ".");
  const nums = [...upper.matchAll(/\d+(?:\.\d+)?/g)].map(match => Number(match[0]));
  if (!nums.length) return NaN;
  const sign = /[SOW]/.test(upper) ? -1 : 1;
  return sign * (nums[0] + (nums[1] || 0) / 60 + (nums[2] || 0) / 3600);
}

async function promptSiteMetadata(site) {
  const address = prompt("Domicilio", site.address || "");
  if (address === null) return;
  const phone = prompt("Telefono", site.phone || "");
  if (phone === null) return;
  const email = prompt("Correo", site.email || "");
  if (email === null) return;
  const region = prompt("Region", site.region || "");
  if (region === null) return;
  const response = await fetch(`/api/sites/${site.id}/metadata`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ address, phone, email, region })
  });
  if (!response.ok) throw new Error(await response.text());
  await refreshData(site.id, state.selectedSiloId);
}

async function updateSiteLocation(siteId, lat, lng, source) {
  const response = await fetch(`/api/sites/${siteId}/location`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lat, lng, location_source: source })
  });
  if (!response.ok) throw new Error(await response.text());
  await refreshData(siteId, state.selectedSiloId);
  map.setView([lat, lng], 18, { animate: true });
}

function updateSiloCalculation() {
  const form = document.getElementById("siloForm");
  const diameter = Number(form.elements.diameter_m.value || 0);
  const height = Number(form.elements.height_m.value || 0);
  const fill = Number(form.elements.fill_percent.value || 0);
  const grain = form.elements.grain.value;
  const densities = { Maiz: 0.72, Trigo: 0.78, Soja: 0.75, Girasol: 0.42, Sorgo: 0.72 };
  const capacity = Math.round(Math.PI * Math.pow(diameter / 2, 2) * height);
  const volume = Math.round(capacity * fill / 100);
  const tons = Math.round(volume * (densities[grain] || 0.72));
  document.getElementById("siloCalc").innerHTML = `
    Capacidad geometrica: <strong>${capacity.toLocaleString("es-AR")} m³</strong><br>
    Volumen con ${fill}% de llenado: <strong>${volume.toLocaleString("es-AR")} m³</strong><br>
    Peso estimado para ${display(grain)}: <strong>${tons.toLocaleString("es-AR")} t</strong>
  `;
}

function selectSite(siteId) {
  const site = state.sites.find(item => item.id === siteId);
  if (!site) return;
  state.selectedSiteId = site.id;
  state.selectedSiloId = (site.silos.filter(matchesSilo)[0] || site.silos[0])?.id || null;
  const select = document.getElementById("siteSelect");
  if (select) select.value = site.id;
  renderAll();
  refreshLiveWeather(site);
}

function selectSilo(siteId, siloId) {
  const site = state.sites.find(item => item.id === siteId);
  const silo = site?.silos.find(item => item.id === siloId);
  if (!silo) return;
  state.selectedSiteId = site.id;
  state.selectedSiloId = silo.id;
  const select = document.getElementById("siteSelect");
  if (select) select.value = site.id;
  renderAll();
  refreshLiveWeather(site);
}

async function refreshLiveWeather(site) {
  if (!site || liveWeatherSiteId === site.id) return;
  liveWeatherSiteId = site.id;
  try {
    const params = new URLSearchParams({
      latitude: site.lat,
      longitude: site.lng,
      current: "temperature_2m,relative_humidity_2m,dew_point_2m,wind_speed_10m,pressure_msl,precipitation",
      timezone: "auto"
    });
    const response = await fetch(`https://api.open-meteo.com/v1/forecast?${params.toString()}`);
    if (!response.ok) throw new Error("Open-Meteo no disponible");
    const payload = await response.json();
    const current = payload.current || {};
    site.weather = {
      ...site.weather,
      recordedAt: current.time || new Date().toISOString(),
      externalTemperature: roundOne(current.temperature_2m),
      externalHumidity: roundOne(current.relative_humidity_2m),
      dewPoint: roundOne(current.dew_point_2m),
      windKmh: roundOne(current.wind_speed_10m),
      pressureHpa: roundOne(current.pressure_msl),
      rainMm: roundOne(current.precipitation),
      source: "Open-Meteo"
    };
    renderMetrics();
    renderDetail();
  } catch (error) {
    console.warn(error);
  } finally {
    liveWeatherSiteId = null;
  }
}

function roundOne(value) {
  return Number.isFinite(Number(value)) ? Math.round(Number(value) * 10) / 10 : 0;
}

function average(values) {
  return values.reduce((sum, value) => sum + Number(value || 0), 0) / Math.max(values.length, 1);
}

function riskClass(status) {
  return status.toLowerCase();
}

function formatDate(date) {
  return new Date(`${date}T12:00:00`).toLocaleDateString("es-AR", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function formatShortTime(value) {
  return new Date(value).toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit" });
}

function daysBetween(date) {
  const start = new Date(`${date}T12:00:00`);
  return Math.max(0, Math.round((Date.now() - start.getTime()) / 86400000));
}

boot().catch(error => {
  document.body.innerHTML = `<main style="padding:24px;color:white"><h1>No se pudo cargar la demo</h1><p>${error.message}</p></main>`;
  console.error(error);
});
