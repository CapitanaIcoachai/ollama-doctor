#!/usr/bin/env python3
"""
ollama-doctor — find out *why* Ollama is slow.

The #1 cause of "Ollama is crawling" is silent CPU offloading: the model (or
part of it) doesn't fit in VRAM, so layers run on the CPU and throughput drops
by 10-50x. Ollama does this quietly. This tool asks the Ollama API what is
actually loaded, shows how much of each model sits in VRAM vs system RAM, and
recommends a model/quant that would fit.

Standard library only. Usage:
    python ollama_doctor.py
"""

import json
import os
import subprocess
import sys
import urllib.request

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")


def _get(path):
    with urllib.request.urlopen(OLLAMA_URL + path, timeout=15) as r:
        return json.loads(r.read())


def _gb(n):
    return n / (1024 ** 3)


def system_ram_gb():
    try:
        if sys.platform == "darwin":
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"])
            return int(out) / (1024 ** 3)
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / (1024 ** 2)  # kB -> GB
    except Exception:
        return None


def main():
    print("=== ollama-doctor ===\n")
    try:
        ps = _get("/api/ps")
    except Exception as e:
        print(f"Cannot reach Ollama at {OLLAMA_URL} ({e}).")
        print("Is `ollama serve` running?")
        return

    ram = system_ram_gb()
    if ram:
        print(f"System RAM: {ram:.1f} GB\n")

    running = ps.get("models", [])
    if not running:
        print("No model is currently loaded. Run one (e.g. `ollama run qwen2.5:7b`)")
        print("and re-run this tool WHILE it is loaded to see the split.\n")
    else:
        print("Loaded models:")
        for m in running:
            size = m.get("size", 0)
            vram = m.get("size_vram", 0)
            on_gpu = (vram / size * 100) if size else 0
            tag = "✅ fully on GPU" if on_gpu >= 99 else (
                "⚠️  PARTIAL CPU OFFLOAD" if on_gpu > 0 else "🐌 FULLY ON CPU")
            print(f"  {m.get('name','?')}")
            print(f"    total {_gb(size):.2f} GB | VRAM {_gb(vram):.2f} GB "
                  f"| {on_gpu:.0f}% on GPU  {tag}")
            if on_gpu < 99:
                print("    → This is your bottleneck. Fix options below.")
        print()

    # recommendations
    print("Recommendations:")
    print("  • Pick a smaller model or a lower quant so the whole model fits VRAM.")
    print("    Rough VRAM need ≈ model params × bytes-per-weight:")
    print("      q4_K_M ≈ 0.5 GB/B params · q8_0 ≈ 1 GB/B · f16 ≈ 2 GB/B")
    print("    e.g. a 7B model at q4_K_M needs ~4.5 GB VRAM (+ context).")
    print("  • Reduce context: `OLLAMA_NUM_CTX` / the `num_ctx` option — KV cache")
    print("    grows with context and eats VRAM.")
    print("  • Keep one model loaded: `OLLAMA_MAX_LOADED_MODELS=1`.")
    print("  • If you have no/low VRAM, accept CPU and use a small model")
    print("    (e.g. 1.5B–3B, q4) — it will be far more responsive than a")
    print("    half-offloaded 7B+.")

    try:
        tags = _get("/api/tags").get("models", [])
        if tags:
            print("\nInstalled models:")
            for t in sorted(tags, key=lambda x: x.get("size", 0)):
                print(f"  {t.get('name','?'):32} {_gb(t.get('size',0)):.2f} GB")
    except Exception:
        pass


if __name__ == "__main__":
    main()
