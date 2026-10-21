"""Samples per-adapter GPU load and dedicated memory through Windows performance counters.

Adapters are identified by LUID, which can change between boots, so the discrete card
is taken to be the adapter with the most dedicated memory in use while a model is loaded.
"""
import json
import subprocess
import threading

_SAMPLER = r"""
$ErrorActionPreference = 'SilentlyContinue'
while ($true) {
  $eng = (Get-Counter '\GPU Engine(*)\Utilization Percentage').CounterSamples
  $mem = (Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples
  $load = @{}
  foreach ($s in $eng) {
    $luid = ([regex]::Match($s.InstanceName, 'luid_0x[0-9a-f]+_0x[0-9a-f]+')).Value
    if ($luid) { $load[$luid] = [double]$load[$luid] + $s.CookedValue }
  }
  $used = @{}
  foreach ($s in $mem) {
    $luid = ([regex]::Match($s.InstanceName, 'luid_0x[0-9a-f]+_0x[0-9a-f]+')).Value
    if ($luid) { $used[$luid] = [double]$used[$luid] + $s.CookedValue }
  }
  [Console]::Out.WriteLine((@{ load = $load; used = $used } | ConvertTo-Json -Compress))
  [Console]::Out.Flush()
}
"""


def snapshot(kind="Dedicated"):
    """Dedicated (or, with kind="Shared", spilled-to-system-RAM) memory in use per adapter, in bytes."""
    script = (f"(Get-Counter '\\GPU Adapter Memory(*)\\{kind} Usage').CounterSamples | "
              "ForEach-Object { $_.InstanceName + '=' + $_.CookedValue }")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True).stdout
    used = {}
    for line in out.splitlines():
        if "=" in line:
            name, value = line.rsplit("=", 1)
            luid = "_".join(name.split("_")[:3])
            used[luid] = used.get(luid, 0.0) + float(value)
    return used


class Sampler:
    """Collects peak load and peak dedicated memory per adapter while running."""

    def __init__(self):
        self.peak_load = {}
        self.peak_used = {}
        self._proc = None
        self._thread = None

    def __enter__(self):
        self._proc = subprocess.Popen(["powershell", "-NoProfile", "-Command", _SAMPLER],
                                      stdout=subprocess.PIPE, text=True,
                                      creationflags=subprocess.CREATE_NO_WINDOW)
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()
        return self

    def _read(self):
        for line in self._proc.stdout:
            try:
                sample = json.loads(line)
            except ValueError:
                continue
            for luid, v in (sample.get("load") or {}).items():
                self.peak_load[luid] = max(self.peak_load.get(luid, 0.0), v)
            for luid, v in (sample.get("used") or {}).items():
                self.peak_used[luid] = max(self.peak_used.get(luid, 0.0), v)

    def __exit__(self, *exc):
        self._proc.kill()
        self._thread.join(timeout=5)

    def summary(self):
        if not self.peak_used:
            return {}
        card = max(self.peak_used, key=self.peak_used.get)
        others = {k: round(v, 1) for k, v in self.peak_load.items() if k != card}
        return {
            "card_peak_load_pct": round(self.peak_load.get(card, 0.0), 1),
            "card_peak_dedicated_gb": round(self.peak_used[card] / 1e9, 2),
            "other_adapters_peak_load_pct": others,
        }
