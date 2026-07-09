"""Pass 3 - human QA sampling helper.

Picks a stratified sample of at least 20 apps (2 per category), prioritising
rows flagged weak by pass 2 and rows with low/medium confidence, and emits a
QA worksheet (data/qa/sample.json). A human (or a supervised re-research
agent) fills in verified answers per field; corrections live in
data/qa/corrections.json with this shape:

    [
      {
        "id": 53,
        "app": "Ahrefs",
        "field": "access_model",
        "original": "self_serve",
        "verified_value": "paid_plan_required",
        "correct": false,
        "correction_made": true,
        "evidence": "https://...",
        "notes": "..."
      }, ...
    ]

Running with --apply merges corrections into data/results.json, marks sampled
rows verified=true, and writes accuracy metrics to data/verification.json.

Usage:
    python pipeline/qa_sample.py            # emit the sample worksheet
    python pipeline/qa_sample.py --apply    # apply corrections + compute metrics
"""

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "data" / "results.json"
EVIDENCE = ROOT / "data" / "evidence_report.json"
QA_DIR = ROOT / "data" / "qa"

CHECKED_FIELDS = [
    "auth_methods",
    "access_model",
    "api_surface_type",
    "mcp_status",
    "buildability_verdict",
    "main_blocker",
]

SAMPLE_PER_CATEGORY = 2


def pick_sample(rows: list[dict]) -> list[dict]:
    flagged = set()
    if EVIDENCE.exists():
        report = json.loads(EVIDENCE.read_text())
        flagged = {r["id"] for r in report["rows"] if r["weak_evidence"]}

    by_cat = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)

    rng = random.Random(42)  # deterministic sample
    sample = []
    for cat, cat_rows in sorted(by_cat.items()):
        # Priority: weak evidence > low confidence > medium > high
        def priority(r):
            return (
                0 if r["id"] in flagged else 1,
                {"low": 0, "medium": 1, "high": 2}[r["confidence"]],
                rng.random(),
            )

        sample.extend(sorted(cat_rows, key=priority)[:SAMPLE_PER_CATEGORY])
    return sample


def emit_worksheet() -> None:
    rows = json.loads(RESULTS.read_text())
    sample = pick_sample(rows)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    worksheet = [
        {
            "id": r["id"],
            "app": r["app"],
            "category": r["category"],
            "fields_to_check": {f: r[f] for f in CHECKED_FIELDS},
            "evidence_urls": r["evidence_urls"],
            "confidence": r["confidence"],
        }
        for r in sample
    ]
    (QA_DIR / "sample.json").write_text(json.dumps(worksheet, indent=2))
    print(f"wrote {QA_DIR / 'sample.json'} ({len(worksheet)} apps, "
          f"{len(worksheet) * len(CHECKED_FIELDS)} field checks)")


def apply_corrections() -> None:
    rows = {r["id"]: r for r in json.loads(RESULTS.read_text())}
    corrections = json.loads((QA_DIR / "corrections.json").read_text())

    checks = len(corrections)
    wrong = [c for c in corrections if not c["correct"]]
    corrected = [c for c in wrong if c.get("correction_made")]
    error_types = Counter(c["field"] for c in wrong)

    sampled_ids = {c["id"] for c in corrections}
    for c in corrections:
        row = rows[c["id"]]
        if c.get("correction_made"):
            row[c["field"]] = c["verified_value"]
            note = f"{c['field']} corrected in QA: {c.get('notes', '')}".strip()
            row["verification_notes"] = (
                (row["verification_notes"] + " | " if row["verification_notes"] else "") + note
            )
        if c.get("evidence") and c["evidence"] not in row["evidence_urls"]:
            row["evidence_urls"].append(c["evidence"])
    for rid in sampled_ids:
        rows[rid]["verified"] = True
        if not rows[rid]["verification_notes"]:
            rows[rid]["verification_notes"] = "Manually verified in QA sample; no corrections needed."

    metrics = {
        "sampled_apps": len(sampled_ids),
        "field_checks": checks,
        "first_pass_correct": checks - len(wrong),
        "first_pass_accuracy": round((checks - len(wrong)) / checks, 4) if checks else None,
        "corrections_made": len(corrected),
        "final_pass_accuracy": round((checks - (len(wrong) - len(corrected))) / checks, 4)
        if checks
        else None,
        "errors_by_field": dict(error_types),
        "corrected_rows": sorted({c["id"] for c in corrected}),
    }
    RESULTS.write_text(json.dumps(sorted(rows.values(), key=lambda r: r["id"]), indent=2, ensure_ascii=False))
    (ROOT / "data" / "verification.json").write_text(
        json.dumps({"metrics": metrics, "qa_table": corrections}, indent=2)
    )
    print(json.dumps(metrics, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        apply_corrections()
    else:
        emit_worksheet()


if __name__ == "__main__":
    main()
