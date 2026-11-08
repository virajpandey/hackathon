import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

from .device import Device, Link

LIE_AFTER = 12  # characters accepted before an injected change

HERE = Path(__file__).resolve().parent
MODEL = json.loads((HERE / "private_lm_model.json").read_text())
PARAMETERS = sum(len(row) if isinstance(row, list) else 1
                 for key in ("E", "W1", "b1", "W2", "b2") for row in MODEL[key])


class Session:
    def __init__(self, specs=None):
        self.specs = specs or ["local"] * 3
        self.processes = []
        self.links = []
        self.lock = threading.Lock()

    def __enter__(self):
        try:
            for spec in self.specs:
                if spec == "local":
                    process = subprocess.Popen(
                        [sys.executable, str(HERE / "node.py"), "0", "--quiet"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    self.processes.append(process)
                    ready = queue.Queue()
                    threading.Thread(target=lambda p=process: ready.put(p.stdout.readline()), daemon=True).start()
                    message = ready.get(timeout=10)
                    if not message:
                        raise RuntimeError("A local worker did not start")
                    port = json.loads(message)["port"]
                    spec = f"tcp:127.0.0.1:{port}"
                self.links.append(Link(spec))
            self.device = Device(self.links, MODEL)
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        for link in self.links:
            link.close()
        self.links = []
        for process in self.processes:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            process.stdout.close()
            process.stderr.close()
        self.processes = []

    def __exit__(self, *args):
        self.close()

    def info(self):
        locations = {name: ("local process" if spec == "local" else
                           "USB chip" if spec.startswith("serial:") else "TCP worker")
                     for name, spec in zip("ABC", self.specs)}
        return {"live": True, "nodes": locations, "parameters": PARAMETERS,
                "client_exchange_phases_per_character": 2}

    def run(self, prompt, lie=None):
        if not isinstance(prompt, str) or len(prompt) > 120:
            raise ValueError("Use a prompt of at most 120 characters")
        prompt = "".join(c for c in prompt.lower() if c in self.device.idx and c != "\n").strip()
        if not prompt:
            raise ValueError("Enter a short note in English")
        if lie not in (None, "A", "B", "C"):
            raise ValueError("Choose node A, B, or C")
        with self.lock:
            normal = self.device.plain_text(prompt)
            # Let some honest text through first so the stop is visible mid-sentence.
            lie_at = max(0, min(LIE_AFTER, len(normal) - len(prompt) - 1))
            start = time.perf_counter()
            result = self.device.run(prompt, lie=f"{lie}@{lie_at}" if lie else None, echo=False)
            elapsed = time.perf_counter() - start
            if lie:
                normal = None
        return {
            "prompt": prompt, "private_text": result["text"], "normal_text": normal,
            "bit_exact": result["exact"] and result["text"] == normal if not lie else None,
            "steps": result["steps"], "caught": result["caught"],
            "attack_node": lie, "rejected_character": result["at"],
            "rejected_view": result.get("rejected_view"),
            "failed_phase": result.get("failed_phase"),
            "client_exchange_phases": result["client_exchange_phases"],
            "elapsed_seconds": round(elapsed, 4),
            "timing_scope": "Private generation including client reference checks; not a serving benchmark",
            "mode": "live", **self.info(),
        }
