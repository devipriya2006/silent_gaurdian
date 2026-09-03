// ---------------------------------------------------------------------
// Silent Guardian — frontend logic
// Handles: video upload analysis + chart, live webcam capture loop
// ---------------------------------------------------------------------

// ---------- Video upload analysis ----------
const dropzone = document.getElementById("dropzone");
const videoInput = document.getElementById("videoInput");
const dropzoneText = document.getElementById("dropzoneText");
const uploadForm = document.getElementById("uploadForm");
const uploadStatus = document.getElementById("uploadStatus");
const uploadResults = document.getElementById("uploadResults");
const analyzeBtn = document.getElementById("analyzeBtn");
let timelineChart = null;

dropzone.addEventListener("click", () => videoInput.click());
["dragover", "dragleave", "drop"].forEach(evt => {
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.toggle("dragover", evt === "dragover");
  });
});
dropzone.addEventListener("drop", (e) => {
  if (e.dataTransfer.files.length) {
    videoInput.files = e.dataTransfer.files;
    dropzoneText.textContent = videoInput.files[0].name;
  }
});
videoInput.addEventListener("change", () => {
  if (videoInput.files.length) {
    dropzoneText.textContent = videoInput.files[0].name;
  }
});

uploadForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!videoInput.files.length) {
    uploadStatus.textContent = "Please choose a video file first.";
    return;
  }

  const formData = new FormData();
  formData.append("video", videoInput.files[0]);

  analyzeBtn.disabled = true;
  uploadStatus.textContent = "Analyzing video… this can take a moment for longer clips.";
  uploadResults.innerHTML = "";

  try {
    const res = await fetch("/api/analyze_video", { method: "POST", body: formData });
    const data = await res.json();

    if (data.error) {
      uploadStatus.textContent = "Error: " + data.error;
      analyzeBtn.disabled = false;
      return;
    }

    uploadStatus.textContent =
      `Analyzed ${data.frames_analyzed} sampled frames — peak score ${data.max_score.toFixed(2)}.`;

    renderTimeline(data.timeline);
    renderIncidents(data.incidents);
  } catch (err) {
    uploadStatus.textContent = "Request failed: " + err.message;
  } finally {
    analyzeBtn.disabled = false;
  }
});

function renderTimeline(timeline) {
  const canvas = document.getElementById("timelineChart");
  canvas.style.display = "block";
  const ctx = canvas.getContext("2d");

  if (timelineChart) timelineChart.destroy();

  timelineChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: timeline.map(p => p.t + "s"),
      datasets: [{
        label: "Violence score",
        data: timeline.map(p => p.score),
        borderColor: "#3ddc97",
        backgroundColor: "rgba(61,220,151,0.15)",
        fill: true,
        tension: 0.25,
        pointRadius: 0,
      }],
    },
    options: {
      responsive: true,
      scales: {
        y: { min: 0, max: 1, ticks: { color: "#8fa3b3" }, grid: { color: "#223140" } },
        x: { ticks: { color: "#8fa3b3", maxTicksLimit: 10 }, grid: { color: "#223140" } },
      },
      plugins: { legend: { labels: { color: "#e8eef4" } } },
    },
  });
}

function renderIncidents(incidents) {
  if (!incidents.length) {
    uploadResults.innerHTML = `<p class="muted" style="margin-top:14px;">No violent activity detected above the threshold.</p>`;
    return;
  }
  const items = incidents.map(inc =>
    `<li>⚠️ Incident #${inc.id} at ${inc.t}s — confidence ${inc.confidence} (${inc.severity})</li>`
  ).join("");
  uploadResults.innerHTML =
    `<p style="margin-top:14px;"><strong>${incidents.length} incident(s) flagged:</strong></p><ul>${items}</ul>
     <p class="muted">View full details, evidence frames, and review actions on the <a href="/dashboard">Dashboard</a>.</p>`;
}

// ---------- Live webcam demo ----------
const webcamVideo = document.getElementById("webcam");
const captureCanvas = document.getElementById("captureCanvas");
const startLiveBtn = document.getElementById("startLive");
const stopLiveBtn = document.getElementById("stopLive");
const scoreBar = document.getElementById("scoreBar");
const scoreValue = document.getElementById("scoreValue");
const liveSeverity = document.getElementById("liveSeverity");
const liveAlert = document.getElementById("liveAlert");

let liveStream = null;
let liveInterval = null;

startLiveBtn.addEventListener("click", async () => {
  try {
    liveStream = await navigator.mediaDevices.getUserMedia({ video: { width: 480, height: 360 } });
    webcamVideo.srcObject = liveStream;
    startLiveBtn.disabled = true;
    stopLiveBtn.disabled = false;
    liveAlert.style.display = "none";

    await fetch("/api/reset_live", { method: "POST" });

    liveInterval = setInterval(captureAndAnalyzeFrame, 600); // ~1.6 fps analysis
  } catch (err) {
    alert("Could not access camera: " + err.message);
  }
});

stopLiveBtn.addEventListener("click", stopLive);

function stopLive() {
  if (liveInterval) clearInterval(liveInterval);
  if (liveStream) {
    liveStream.getTracks().forEach(t => t.stop());
  }
  startLiveBtn.disabled = false;
  stopLiveBtn.disabled = true;
}

async function captureAndAnalyzeFrame() {
  if (!webcamVideo.videoWidth) return;

  captureCanvas.width = webcamVideo.videoWidth;
  captureCanvas.height = webcamVideo.videoHeight;
  const ctx = captureCanvas.getContext("2d");
  ctx.drawImage(webcamVideo, 0, 0, captureCanvas.width, captureCanvas.height);
  const dataUrl = captureCanvas.toDataURL("image/jpeg", 0.7);

  try {
    const res = await fetch("/api/analyze_frame", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image: dataUrl }),
    });
    const data = await res.json();
    if (data.error) return;

    updateLiveUI(data);
  } catch (err) {
    // silent fail on a single frame; keep the loop going
  }
}

function updateLiveUI(data) {
  const pct = Math.round(data.score * 100);
  scoreBar.style.width = pct + "%";
  scoreValue.textContent = data.score.toFixed(2);

  liveSeverity.textContent = data.severity;
  liveSeverity.className = "severity-tag severity-" + data.severity.toLowerCase();

  if (data.incident) {
    liveAlert.style.display = "block";
    liveAlert.innerHTML =
      `🚨 <strong>Incident #${data.incident.id} logged</strong> — confidence ${data.incident.confidence}. ` +
      `Check the <a href="/dashboard" style="color:#ffb3b3;">Dashboard</a> for evidence.`;
  }
}

window.addEventListener("beforeunload", stopLive);
