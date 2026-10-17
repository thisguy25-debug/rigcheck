"""
Fan speeds set from RigCheck, with safety rails.

The speeds go through LibreHardwareMonitor, the sensor helper RigCheck already uses for
temperatures. Rules that keep this safe:

* A fan you haven't touched stays on automatic (the motherboard's or graphics card's own curve).
* Pumps never go below 60%, graphics card fans never below 30%, other fans never below 20%.
* While any fan is set by hand, RigCheck watches temperatures every 2 seconds. If the processor
  reaches 90 °C or the graphics card 87 °C, every fan goes back to automatic straight away.
* Closing RigCheck puts every fan back to automatic. If Windows shuts down with RigCheck still
  open, the sensor helper's startup script clears the saved speeds at the next sign-in.
"""

import threading
import time

import sensors

CPU_LIMIT = 90
GPU_LIMIT = 87
CHECK_EVERY = 2.0


def clamp(percent, kind):
    return max(sensors.MIN_PERCENT.get(kind, 20), min(100, round(percent)))


class FanController:
    def __init__(self, on_event=None):
        """on_event(message) is called from a background thread when the guard steps in."""
        self.on_event = on_event or (lambda msg: None)
        self.profile = {}      # sensor id -> percent the user chose (missing = automatic)
        self.kinds = {}        # sensor id -> "fan" / "pump" / "gpu"
        self.applied = set()   # ids RigCheck has set by hand right now
        self.lock = threading.Lock()
        self.tripped = None    # message, once the guard has handed fans back
        self._hot = 0
        self._stop = threading.Event()
        self._thread = None
        self.last = None       # latest {'controls', 'cpu_temp', 'gpu_temp'} for the window

    # ------------------------------------------------------------ changes
    def set(self, sensor_id, percent, kind="fan"):
        """Set one fan (percent) or hand it back to automatic (None). Returns True if accepted."""
        self.kinds[sensor_id] = kind
        with self.lock:
            if percent is None:
                self.profile.pop(sensor_id, None)
                ok = sensors.set_control(sensor_id, None)
                self.applied.discard(sensor_id)
                return ok
            percent = clamp(percent, kind)
            self.profile[sensor_id] = percent
            self.tripped = None
            ok = sensors.set_control(sensor_id, percent)
            if ok:
                self.applied.add(sensor_id)
        self._ensure_thread()
        return ok

    def load(self, profile, kinds=None):
        """Re-apply saved speeds once the sensor helper answers (called when RigCheck starts)."""
        self.profile = dict(profile or {})
        self.kinds.update(kinds or {})
        if self.profile:
            self._ensure_thread()

    def all_auto(self):
        with self.lock:
            ids = set(self.applied) | set(self.profile)
            self.profile.clear()
            for sid in ids:
                sensors.set_control(sid, None)
            self.applied.clear()

    def shutdown(self):
        """RigCheck is closing: every fan goes back to automatic."""
        self._stop.set()
        with self.lock:
            for sid in list(self.applied):
                sensors.set_control(sid, None)
            self.applied.clear()

    # ------------------------------------------------------------ guard
    def _ensure_thread(self):
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                pass
            if not self.profile and not self.applied:
                return
            self._stop.wait(CHECK_EVERY)

    def tick(self):
        all_sensors = sensors.read_sensors(timeout=1)
        if all_sensors is None:
            self.last = None
            return
        info = sensors.pick(all_sensors, sensors.PREFERRED_FAN)
        controls = sensors.fan_controls(all_sensors)
        self.last = {"controls": controls, "cpu_temp": info.get("cpu_temp"), "gpu_temp": info.get("gpu_temp")}
        for c in controls:
            self.kinds.setdefault(c["id"], c["kind"])
        if not self.profile:
            return
        cpu, gpu = info.get("cpu_temp") or 0, info.get("gpu_temp") or 0
        hot = cpu >= CPU_LIMIT or gpu >= GPU_LIMIT
        self._hot = self._hot + 1 if hot else 0
        if self._hot >= 2:  # two readings in a row, so a single spike doesn't trip it
            part, temp = ("processor", cpu) if cpu >= CPU_LIMIT else ("graphics card", gpu)
            self.all_auto()
            self.tripped = (f"Your {part} reached {temp:.0f} °C, so RigCheck put every fan back on "
                            "automatic. Your settings are saved; turn them on again in Fan control.")
            self._hot = 0
            self.on_event(self.tripped)
            return
        # (Re)apply: after RigCheck starts, or if the sensor helper restarted and forgot them
        present = {c["id"]: c for c in controls}
        with self.lock:
            for sid, want in list(self.profile.items()):
                c = present.get(sid)
                if c is None:
                    continue
                if sid not in self.applied or c["percent"] is None or abs(c["percent"] - want) > 3:
                    if sensors.set_control(sid, clamp(want, self.kinds.get(sid, "fan"))):
                        self.applied.add(sid)

    def status(self):
        return self.tripped
