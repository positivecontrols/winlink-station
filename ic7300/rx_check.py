"""
Verify the whole receive chain: antenna -> radio -> USB codec -> ALSA -> decoder.

RECEIVE ONLY. Nothing here keys the transmitter. Tune the radio to a busy FT8
frequency first. Needs jt9 from WSJT-X.

If the receiver isn't delivering usable audio, an ARDOP session fails in exactly
the same way as a bad transmitter -- we call, the gateway answers, we don't hear
it, and we time out with no error that points anywhere useful.

FT8 is the ideal probe: the calling frequency is busy at essentially all hours,
transmissions are strictly aligned to 15-second boundaries, and jt9 gives an
unambiguous pass/fail with signal reports attached.
"""

from __future__ import annotations

import subprocess
import sys
import time
import wave

import numpy as np

CAPTURE = "plughw:CODEC,0"
RATE = 12000  # what jt9 expects; plughw resamples from the codec's native rate
PERIOD = 15.0
RECORD_SECONDS = 13.5
WAV = "/tmp/rx_check.wav"


def wait_for_window() -> None:
    """Sleep until the start of the next FT8 transmit period."""
    now = time.time()
    wait = PERIOD - (now % PERIOD)
    print(f"  waiting {wait:.1f}s for the next FT8 window...")
    time.sleep(wait)


def record() -> None:
    subprocess.run(
        [
            "arecord", "-D", CAPTURE,
            "-f", "S16_LE", "-r", str(RATE), "-c", "1",
            "-d", str(int(RECORD_SECONDS)), WAV,
        ],
        capture_output=True,
        check=True,
    )


def audio_stats() -> dict[str, float]:
    with wave.open(WAV) as w:
        raw = w.readframes(w.getnframes())
        rate = w.getframerate()
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
    if samples.size == 0:
        return {"rms": 0.0, "peak": 0.0, "pct_fs": 0.0, "rate": rate}

    rms = float(np.sqrt(np.mean(samples**2)))
    peak = float(np.max(np.abs(samples)))
    return {
        "rms": rms,
        "peak": peak,
        "pct_fs": peak * 100.0 / 32767.0,
        "rate": float(rate),
    }


def spectrum_peaks(top: int = 5) -> list[tuple[float, float]]:
    """Strongest audio frequencies present, as a sanity check on the passband."""
    with wave.open(WAV) as w:
        raw = w.readframes(w.getnframes())
        rate = w.getframerate()
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
    if samples.size < 1024:
        return []
    window = np.hanning(samples.size)
    spec = np.abs(np.fft.rfft(samples * window))
    freqs = np.fft.rfftfreq(samples.size, 1.0 / rate)
    # Ignore DC and anything outside the SSB passband.
    mask = (freqs > 100) & (freqs < 3500)
    spec, freqs = spec[mask], freqs[mask]
    idx = np.argsort(spec)[-top:][::-1]
    return [(float(freqs[i]), float(spec[i])) for i in idx]


def decode() -> str:
    result = subprocess.run(
        ["jt9", "-8", WAV], capture_output=True, text=True, timeout=90
    )
    return (result.stdout or "") + (result.stderr or "")


def main() -> int:
    cycles = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    total_decodes = 0

    for cycle in range(1, cycles + 1):
        print(f"\n--- cycle {cycle}/{cycles} ---")
        wait_for_window()
        print("  recording...")
        record()

        stats = audio_stats()
        print(f"  audio: RMS {stats['rms']:.0f}  peak {stats['peak']:.0f} "
              f"({stats['pct_fs']:.1f}% of full scale) @ {stats['rate']:.0f} Hz")

        if stats["peak"] < 100:
            print("  !! essentially silent - no audio reaching the computer")
        elif stats["pct_fs"] > 95:
            print("  !! clipping - receive audio is too hot")

        peaks = spectrum_peaks()
        if peaks:
            shown = ", ".join(f"{f:.0f}Hz" for f, _ in peaks)
            print(f"  strongest audio tones: {shown}")

        out = decode().strip()
        lines = [ln for ln in out.splitlines() if ln.strip()]
        if lines:
            total_decodes += len(lines)
            print(f"  DECODED {len(lines)} FT8 signals:")
            for line in lines[:12]:
                print(f"    {line}")
        else:
            print("  no FT8 decodes this cycle")

    print(f"\n==> total decodes: {total_decodes}")
    if total_decodes:
        print("==> RECEIVE CHAIN IS GOOD: antenna -> radio -> USB -> ALSA -> decoder")
    else:
        print("==> NO DECODES: receive chain is suspect (or the band is dead)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
