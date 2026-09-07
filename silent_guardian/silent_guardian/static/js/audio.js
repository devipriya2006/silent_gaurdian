// ---------------------------------------------------------------------
// Silent Guardian — Audio page logic
// Handles: WAV file upload, and mic recording encoded to WAV client-side
// (via Web Audio API) so the server only ever has to read plain WAV —
// no ffmpeg/codec dependency needed on the backend.
// ---------------------------------------------------------------------

const audioDropzone = document.getElementById("audioDropzone");
const audioInput = document.getElementById("audioInput");
const audioDropzoneText = document.getElementById("audioDropzoneText");
const audioUploadForm = document.getElementById("audioUploadForm");
const analyzeAudioBtn = document.getElementById("analyzeAudioBtn");
const audioStatus = document.getElementById("audioStatus");

audioDropzone.addEventListener("click", () => audioInput.click());
audioInput.addEventListener("change", () => {
  if (audioInput.files.length) {
    audioDropzoneText.textContent = audioInput.files[0].name;
  }
});

audioUploadForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!audioInput.files.length) {
    audioStatus.textContent = "Please choose a .wav file first.";
    return;
  }
  await sendAudioBlob(audioInput.files[0], "upload");
});

// ---------- Microphone recording ----------
const startRecordBtn = document.getElementById("startRecord");
const stopRecordBtn = document.getElementById("stopRecord");
const recordStatus = document.getElementById("recordStatus");

let audioCtx = null;
let mediaStream = null;
let sourceNode = null;
let processorNode = null;
let recordedChunks = [];
let recordingSampleRate = 44100;

startRecordBtn.addEventListener("click", async () => {
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    recordingSampleRate = audioCtx.sampleRate;

    sourceNode = audioCtx.createMediaStreamSource(mediaStream);
    processorNode = audioCtx.createScriptProcessor(4096, 1, 1);
    recordedChunks = [];

    processorNode.onaudioprocess = (e) => {
      const input = e.inputBuffer.getChannelData(0);
      recordedChunks.push(new Float32Array(input));
    };

    sourceNode.connect(processorNode);
    processorNode.connect(audioCtx.destination);

    startRecordBtn.disabled = true;
    stopRecordBtn.disabled = false;
    recordStatus.textContent = "🔴 Recording…";
  } catch (err) {
    alert("Could not access microphone: " + err.message);
  }
});

stopRecordBtn.addEventListener("click", async () => {
  processorNode.disconnect();
  sourceNode.disconnect();
  mediaStream.getTracks().forEach(t => t.stop());

  startRecordBtn.disabled = false;
  stopRecordBtn.disabled = true;
  recordStatus.textContent = "Encoding & analyzing…";

  const wavBlob = encodeWav(recordedChunks, recordingSampleRate);
  await sendAudioBlob(wavBlob, "recording", "recording.wav");
  recordStatus.textContent = "";
});

function encodeWav(chunks, sampleRate) {
  let length = 0;
  chunks.forEach(c => (length += c.length));

  const merged = new Float32Array(length);
  let offset = 0;
  chunks.forEach(c => {
    merged.set(c, offset);
    offset += c.length;
  });

  const buffer = new ArrayBuffer(44 + merged.length * 2);
  const view = new DataView(buffer);

  writeString(view, 0, "RIFF");
  view.setUint32(4, 36 + merged.length * 2, true);
  writeString(view, 8, "WAVE");
  writeString(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(view, 36, "data");
  view.setUint32(40, merged.length * 2, true);

  let idx = 44;
  for (let i = 0; i < merged.length; i++) {
    const s = Math.max(-1, Math.min(1, merged[i]));
    view.setInt16(idx, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    idx += 2;
  }

  return new Blob([view], { type: "audio/wav" });
}

function writeString(view, offset, str) {
  for (let i = 0; i < str.length; i++) {
    view.setUint8(offset + i, str.charCodeAt(i));
  }
}

// ---------- Shared: send + render ----------
async function sendAudioBlob(blob, sourceLabel, filename) {
  const formData = new FormData();
  formData.append("audio", blob, filename || (blob.name || "audio.wav"));

  analyzeAudioBtn.disabled = true;
  audioStatus.textContent = "Analyzing audio…";
  document.getElementById("audioResults").style.display = "none";

  try {
    const res = await fetch("/api/analyze_audio", { method: "POST", body: formData });
    const data = await readApiResponse(res);

    if (data.error) {
      audioStatus.textContent = "Error: " + data.error;
      return;
    }

    audioStatus.textContent = "Analysis complete.";
    renderAudioResult(data);
  } catch (err) {
    audioStatus.textContent = "Request failed: " + err.message;
  } finally {
    analyzeAudioBtn.disabled = false;
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

function renderAudioResult(data) {
  const panel = document.getElementById("audioResults");
  panel.style.display = "block";

  document.getElementById("audioScoreBar").style.width = data.score + "%";
  document.getElementById("audioScoreValue").textContent = data.score.toFixed(1) + " / 100";

  const sev = document.getElementById("audioSeverity");
  sev.textContent = data.level;
  sev.className = "severity-tag severity-" + data.level.toLowerCase();

  document.getElementById("audioCategory").textContent = data.category;
  document.getElementById("audioDuration").textContent = data.duration_sec + "s";
  document.getElementById("audioPeakTime").textContent = data.peak_time_sec + "s";

  const alertBox = document.getElementById("audioAlert");
  if (data.incident) {
    alertBox.style.display = "block";
    alertBox.innerHTML =
      `🚨 <strong>Incident #${data.incident.id} logged</strong> for human review. ` +
      `See the <a href="/dashboard" style="color:#ffb3b3;">Dashboard</a>.`;
  } else {
    alertBox.style.display = "none";
  }
}
