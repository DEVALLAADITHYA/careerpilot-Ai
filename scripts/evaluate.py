"""Usage: python scripts/evaluate.py <report.json> [labels.json]
labels.json = {"<job_id>": true|false}  (manually reviewed: is the job really open?)"""
import json
import sys

from app.services import evaluation as ev

rep = json.load(open(sys.argv[1]))
res = rep["results"]
out = {
    "n_results": len(res),
    "duplicate_rate": ev.duplicate_rate([r["job"]["source_url"] for r in res]),
    "link_accessibility": ev.link_accessibility([r["verification"]["status"] for r in res if r["verification"]]),
}
if len(sys.argv) > 2:
    truth = json.load(open(sys.argv[2]))
    out["verification"] = ev.verification_precision(
        {r["job"]["job_id"]: r["verification"]["status"] for r in res if r["verification"]}, truth)
print(json.dumps(out, indent=2))
