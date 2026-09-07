"""
Audio-based distress / aggressive-event indicator analysis.

Deliberately built on the Python standard library `wave` module plus
NumPy only — no librosa/ffmpeg dependency — so it stays light enough
for Render's free tier and has nothing extra to fail to install.

Because of this, the analyzer expects PCM WAV audio. The browser-side
recorder (static/js/audio.js) captures microphone audio via the Web
Audio API and encodes it to WAV client-side before upload, so both the
"record" and "upload a file" paths land here as WAV bytes.

What it measures (all on short analysis windows across the clip):
  - RMS energy                 : overall loudness
  - energy spike ratio          : how much louder the loud parts are
                                   vs. the clip's own baseline (a sudden
                                   scream/shout stands out from ambient
                                   noise; a uniformly loud recording does
                                   not)
  - zero-crossing rate (ZCR)    : how "harsh"/noisy vs. tonal the sound
                                   is — screaming and shouting tend to
                                   have higher, more erratic ZCR than
                                   calm speech
  - spectral energy spread      : a coarse FFT-based measure of how much
                                   energy sits in higher frequencies,
                                   which rises for shouting/screaming
                                   relative to normal speech

These combine into a single 0-100 score via the same philosophy as the
video detector: adaptive to the clip's own baseline, not a fixed
universal threshold, and explicitly NOT a claim that any acoustic
category (e.g. "shouting") equals violence.
"""

import io
import wave

import numpy as np

WINDOW_SECONDS = 0.5


def _read_wav(file_bytes):
    with wave.open(io.BytesIO(file_bytes), "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    dtype_map = {1: np.uint8, 2: np.int16, 4: np.int32}
    if sampwidth not in dtype_map:
        raise ValueError(f"Unsupported WAV sample width: {sampwidth} bytes")

    samples = np.frombuffer(raw, dtype=dtype_map[sampwidth]).astype(np.float32)
    if sampwidth == 1:
        samples -= 128.0  # uint8 WAV is unsigned, centered at 128

    if n_channels > 1:
        samples = samples.reshape(-1, n_channels).mean(axis=1)

    peak = float(np.max(np.abs(samples))) or 1.0
    samples = samples / peak
    return samples, framerate


def analyze_audio_bytes(file_bytes):
    """
    Returns a dict with the 0-100 raw score, a category label, and
    supporting stats — or raises ValueError for unreadable audio.
    """
    samples, framerate = _read_wav(file_bytes)
    duration_sec = len(samples) / float(framerate)

    if duration_sec < 0.3:
        raise ValueError("Audio clip is too short to analyze (minimum ~0.3s).")

    window_len = max(1, int(WINDOW_SECONDS * framerate))
    n_windows = max(1, len(samples) // window_len)

    energies = []
    zcrs = []
    highfreq_ratios = []

    for i in range(n_windows):
        chunk = samples[i * window_len:(i + 1) * window_len]
        if len(chunk) == 0:
            continue

        rms = float(np.sqrt(np.mean(chunk ** 2)))
        energies.append(rms)

        signs = np.sign(chunk)
        signs[signs == 0] = 1
        zcr = float(np.mean(signs[:-1] != signs[1:])) if len(signs) > 1 else 0.0
        zcrs.append(zcr)

        spectrum = np.abs(np.fft.rfft(chunk))
        if spectrum.sum() > 0:
            split = len(spectrum) // 3
            high_energy = spectrum[split * 2:].sum()
            highfreq_ratios.append(float(high_energy / spectrum.sum()))
        else:
            highfreq_ratios.append(0.0)

    energies = np.array(energies)
    zcrs = np.array(zcrs)
    highfreq_ratios = np.array(highfreq_ratios)

    mean_energy = float(np.mean(energies))
    peak_energy = float(np.max(energies))
    baseline = float(np.percentile(energies, 40)) + 1e-6
    energy_spike_ratio = float(peak_energy / baseline)

    mean_zcr = float(np.mean(zcrs))
    max_zcr = float(np.max(zcrs))
    mean_highfreq = float(np.mean(highfreq_ratios))

    # Normalize each signal into 0-1 with generous, documented caps,
    # then combine. Tuned to be conservative (favor MODERATE over
    # CRITICAL for ambiguous clips) rather than alarmist.
    n_spike = _clip01((energy_spike_ratio - 1.5) / 6.0)
    n_loud = _clip01((mean_energy - 0.05) / 0.35)
    n_zcr = _clip01((max_zcr - 0.05) / 0.35)
    n_hf = _clip01((mean_highfreq - 0.15) / 0.5)

    raw = 0.35 * n_spike + 0.25 * n_loud + 0.20 * n_zcr + 0.20 * n_hf
    score = float(_clip01(raw) * 100)

    if score < 30:
        category = "Normal / background audio"
    elif score < 50:
        category = "Possible distress"
    elif score < 75:
        category = "Possible aggressive / high-intensity event"
    else:
        category = "High-confidence potential emergency / distress event"

    # Rough timestamp of the loudest window, for the "when it happened" field
    peak_window_idx = int(np.argmax(energies)) if len(energies) else 0
    peak_time_sec = round(peak_window_idx * WINDOW_SECONDS, 2)

    return {
        "score": round(score, 1),
        "category": category,
        "duration_sec": round(duration_sec, 2),
        "peak_time_sec": peak_time_sec,
        "stats": {
            "mean_energy": round(mean_energy, 4),
            "energy_spike_ratio": round(energy_spike_ratio, 2),
            "mean_zcr": round(mean_zcr, 4),
            "mean_highfreq_ratio": round(mean_highfreq, 4),
        },
    }


def _clip01(x):
    return max(0.0, min(1.0, x))
