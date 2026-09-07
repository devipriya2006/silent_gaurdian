// ---------------------------------------------------------------------
// Silent Guardian — Image page logic
// ---------------------------------------------------------------------

const imageDropzone = document.getElementById("imageDropzone");
const imageInput = document.getElementById("imageInput");
const imageDropzoneText = document.getElementById("imageDropzoneText");
const imageUploadForm = document.getElementById("imageUploadForm");
const analyzeImageBtn = document.getElementById("analyzeImageBtn");
const imageStatus = document.getElementById("imageStatus");
const imagePreview = document.getElementById("imagePreview");

imageDropzone.addEventListener("click", () => imageInput.click());
["dragover", "dragleave", "drop"].forEach(evt => {
  imageDropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    imageDropzone.classList.toggle("dragover", evt === "dragover");
  });
});
imageDropzone.addEventListener("drop", (e) => {
  if (e.dataTransfer.files.length) {
    imageInput.files = e.dataTransfer.files;
    handleImageSelected();
  }
});
imageInput.addEventListener("change", handleImageSelected);

function handleImageSelected() {
  if (!imageInput.files.length) return;
  const file = imageInput.files[0];
  imageDropzoneText.textContent = file.name;

  const reader = new FileReader();
  reader.onload = (e) => {
    imagePreview.src = e.target.result;
    imagePreview.style.display = "block";
  };
  reader.readAsDataURL(file);
}

imageUploadForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!imageInput.files.length) {
    imageStatus.textContent = "Please choose an image first.";
    return;
  }

  const formData = new FormData();
  formData.append("image", imageInput.files[0]);

  analyzeImageBtn.disabled = true;
  imageStatus.textContent = "Analyzing image…";
  document.getElementById("imageResults").style.display = "none";

  try {
    const res = await fetch("/api/analyze_image", { method: "POST", body: formData });
    const data = await readApiResponse(res);

    if (data.error) {
      imageStatus.textContent = "Error: " + data.error;
      return;
    }

    imageStatus.textContent = "Analysis complete.";
    renderImageResult(data);
  } catch (err) {
    imageStatus.textContent = "Request failed: " + err.message;
  } finally {
    analyzeImageBtn.disabled = false;
  }
});

function renderImageResult(data) {
  const panel = document.getElementById("imageResults");
  panel.style.display = "block";

  document.getElementById("imageScoreBar").style.width = data.score + "%";
  document.getElementById("imageScoreValue").textContent = data.score.toFixed(1) + " / 100";

  const sev = document.getElementById("imageSeverity");
  sev.textContent = data.level;
  sev.className = "severity-tag severity-" + data.level.toLowerCase();

  document.getElementById("imgEdgeDensity").textContent = data.stats.edge_density;
  document.getElementById("imgContrast").textContent = data.stats.contrast;
  document.getElementById("imgTexture").textContent = data.stats.texture_complexity;

  const alertBox = document.getElementById("imageAlert");
  if (data.incident) {
    alertBox.style.display = "block";
    alertBox.innerHTML =
      `🚨 <strong>Incident #${data.incident.id} logged</strong> for human review. ` +
      `See the <a href="/dashboard" style="color:#ffb3b3;">Dashboard</a>.`;
  } else {
    alertBox.style.display = "none";
  }
}

async function readApiResponse(response) {
  const body = await response.text();
  try {
    const data = JSON.parse(body);
    if (!response.ok && !data.error) data.error = `Request failed (${response.status}).`;
    return data;
  } catch (_) {
    return { error: `The server returned an unexpected response (${response.status}). Please try again.` };
  }
}
