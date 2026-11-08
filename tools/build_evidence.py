import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
data = json.loads((ROOT / "web/data/quality.json").read_text())
model = json.loads((ROOT / "engine/private_lm_model.json").read_text())
a, b = data["standard"], data["escape1_ours"]
numbers = {
    "demo_parameters": sum(len(row) if isinstance(row, list) else 1
                           for key in ("E", "W1", "b1", "W2", "b2") for row in model[key]),
    "research_parameters": a["params"],
    "training_tokens": data["unique_tokens_trained"],
    "baseline_loss": a["final_val_loss"],
    "private_friendly_loss": b["final_val_loss"],
    "baseline_perplexity": a["final_val_ppl"],
    "private_friendly_perplexity": b["final_val_ppl"],
    "perplexity_increase_percent": round(100 * math.expm1(b["final_val_loss"] - a["final_val_loss"]), 2),
    "source": "web/data/quality.json; historical training result, not a private inference benchmark",
}
(ROOT / "web/data/numbers.json").write_text(json.dumps(numbers, indent=2) + "\n")
labels = [("Standard model", a["final_val_ppl"], "#99988f"),
          ("Private-friendly model", b["final_val_ppl"], "#191918")]
parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="430" viewBox="0 0 1000 430" role="img" aria-labelledby="title">',
         '<title id="title">Held-out perplexity: standard 61.57, private-friendly 63.10. Lower is better.</title>',
         '<g font-family="monospace" fill="#191918" transform="translate(40 0)">',
         '<text x="0" y="30" font-size="23">HELD-OUT PERPLEXITY · LOWER IS BETTER</text>']
for i, (label, value, color) in enumerate(labels):
    y = 105 + 155 * i
    width = value / 70 * 760
    parts += [f'<text x="0" y="{y}" font-size="28">{label}</text>',
              f'<rect x="0" y="{y+20}" width="{width:.3f}" height="56" fill="{color}"/>',
              f'<text x="{width+20:.3f}" y="{y+60}" font-size="34">{value:.2f}</text>']
parts += ['<path d="M0 360H760" stroke="#62625c"/>']
for tick in (0, 20, 40, 60, 70):
    x = tick / 70 * 760
    parts += [f'<path d="M{x:.3f} 360v8" stroke="#62625c"/>',
              f'<text x="{x:.3f}" y="400" font-size="21" text-anchor="middle">{tick}</text>']
parts += ["</g></svg>"]
(ROOT / "web/assets/quality.svg").write_text("\n".join(parts) + "\n")
print(json.dumps(numbers, indent=2))
