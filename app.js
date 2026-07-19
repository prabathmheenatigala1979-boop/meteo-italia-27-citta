const DATA_URL = `data/weather.json?v=${Date.now()}`;

const grid = document.querySelector("#city-grid");
const loading = document.querySelector("#loading");
const errorBox = document.querySelector("#error");
const errorMessage = document.querySelector("#error-message");
const searchInput = document.querySelector("#city-search");
const resultCount = document.querySelector("#result-count");
const updateLabel = document.querySelector("#update-label");
const modelRun = document.querySelector("#model-run");
const notice = document.querySelector("#notice");
const attribution = document.querySelector("#attribution");
const statusDot = document.querySelector("#status-dot");

let allCities = [];

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDate(isoDate) {
  const date = new Date(`${isoDate}T12:00:00`);
  return new Intl.DateTimeFormat("it-IT", {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
  }).format(date);
}

function numberOrDash(value, suffix = "") {
  return Number.isFinite(value) ? `${Math.round(value)}${suffix}` : "—";
}

function cityCard(city) {
  const days = city.forecast.map((day) => `
    <article class="day">
      <div class="weather-icon" aria-hidden="true">${escapeHtml(day.icon)}</div>
      <div>
        <div class="day-top">
          <span class="day-label">${escapeHtml(day.day_label)}</span>
          <span class="day-date">${escapeHtml(formatDate(day.date))}</span>
        </div>
        <p class="description">${escapeHtml(day.description)}</p>
        <div class="metrics">
          <span class="metric temperature">
            ${numberOrDash(day.temperature_min_c, "°")} / ${numberOrDash(day.temperature_max_c, "°")}
          </span>
          <span class="metric">Pioggia: ${numberOrDash(day.precipitation_mm, " mm")}</span>
          <span class="metric">Vento: ${numberOrDash(day.wind_max_kmh, " km/h")}</span>
        </div>
      </div>
    </article>
  `).join("");

  return `
    <section class="city-card">
      <div class="city-heading">
        <h2>${escapeHtml(city.name)}</h2>
        <span class="region">${escapeHtml(city.region)}</span>
      </div>
      <div class="days">${days}</div>
    </section>
  `;
}

function render(cities) {
  grid.innerHTML = cities.map(cityCard).join("");
  resultCount.textContent = cities.length === 1
    ? "1 città visualizzata"
    : `${cities.length} città visualizzate`;

  if (cities.length === 0) {
    grid.innerHTML = `
      <section class="state-card">
        <h2>Nessuna città trovata</h2>
        <p>Prova con un altro nome o con una regione.</p>
      </section>
    `;
  }
}

function applyFilter() {
  const query = searchInput.value.trim().toLocaleLowerCase("it");
  if (!query) {
    render(allCities);
    return;
  }

  const filtered = allCities.filter((city) =>
    `${city.name} ${city.region}`.toLocaleLowerCase("it").includes(query)
  );
  render(filtered);
}

async function loadWeather() {
  try {
    const response = await fetch(DATA_URL, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Errore HTTP ${response.status}`);
    }

    const data = await response.json();
    if (data.status !== "ok" || !Array.isArray(data.cities) || data.cities.length !== 27) {
      throw new Error("Il file meteo non contiene un aggiornamento completo.");
    }

    allCities = [...data.cities].sort((a, b) =>
      a.name.localeCompare(b.name, "it")
    );

    updateLabel.textContent = `Ultimo aggiornamento automatico: ${data.generated_at_label}, ora italiana`;
    modelRun.textContent = `Run del modello: ${data.model_run_label}`;
    notice.textContent = data.notice_it;
    attribution.textContent = data.attribution;
    statusDot.classList.add("ok");

    loading.hidden = true;
    errorBox.hidden = true;
    render(allCities);
  } catch (error) {
    console.error(error);
    loading.hidden = true;
    errorBox.hidden = false;
    errorMessage.textContent =
      "L'aggiornamento automatico non è ancora disponibile oppure è temporaneamente in ritardo. " +
      "La pagina non pubblica valori incompleti.";
    updateLabel.textContent = "Aggiornamento non disponibile";
    modelRun.textContent = "";
  }
}

searchInput.addEventListener("input", applyFilter);
loadWeather();
