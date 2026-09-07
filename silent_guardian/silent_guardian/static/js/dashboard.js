// ---------------------------------------------------------------------
// Silent Guardian — Dashboard filtering + review actions
// ---------------------------------------------------------------------

function reviewIncident(id, status) {
  fetch(`/api/incidents/${id}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  }).then(() => {
    const row = document.getElementById(`row-${id}`);
    const tag = row.querySelector(".status-tag");
    tag.textContent = status;
    tag.className = `status-tag status-${status.replace(" ", "_")}`;
    row.dataset.status = status;
  });
}

const filterSource = document.getElementById("filterSource");
const filterClassification = document.getElementById("filterClassification");
const filterStatus = document.getElementById("filterStatus");
const filterDateFrom = document.getElementById("filterDateFrom");
const filterDateTo = document.getElementById("filterDateTo");
const clearFiltersBtn = document.getElementById("clearFilters");
const table = document.getElementById("incidentTable");
const noResultsMsg = document.getElementById("noResultsMsg");

function applyFilters() {
  if (!table) return;
  const rows = table.querySelectorAll("tbody tr");
  const src = filterSource.value;
  const cls = filterClassification.value;
  const status = filterStatus.value;
  const dateFrom = filterDateFrom.value;
  const dateTo = filterDateTo.value;

  let visibleCount = 0;

  rows.forEach(row => {
    let visible = true;

    if (src && row.dataset.source !== src) visible = false;
    if (cls && row.dataset.classification !== cls) visible = false;
    if (status && row.dataset.status !== status) visible = false;
    if (dateFrom && row.dataset.date < dateFrom) visible = false;
    if (dateTo && row.dataset.date > dateTo) visible = false;

    row.style.display = visible ? "" : "none";
    if (visible) visibleCount++;
  });

  if (noResultsMsg) {
    noResultsMsg.style.display = visibleCount === 0 ? "block" : "none";
  }
}

[filterSource, filterClassification, filterStatus, filterDateFrom, filterDateTo].forEach(el => {
  if (el) el.addEventListener("change", applyFilters);
});

if (clearFiltersBtn) {
  clearFiltersBtn.addEventListener("click", () => {
    filterSource.value = "";
    filterClassification.value = "";
    filterStatus.value = "";
    filterDateFrom.value = "";
    filterDateTo.value = "";
    applyFilters();
  });
}
