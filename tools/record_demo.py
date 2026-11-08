import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.session import Session

with Session() as session:
    honest = session.run("patient reports chest")
    tampered = session.run("patient reports chest", "B")
if not honest["bit_exact"] or not tampered["caught"]:
    raise RuntimeError("Refusing to record a failed verification")
for result in (honest, tampered):
    result["mode"] = "recorded"
    result["live"] = False
data = {"recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "source": "Three local TCP worker processes; synthetic input; actual protocol execution",
        "honest": honest, "tampered": tampered}
target = ROOT / "web/data/recording.json"
target.write_text(json.dumps(data, indent=2) + "\n")
print(f"Saved verified recording: {target}")
