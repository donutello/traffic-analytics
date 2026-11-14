"""Every code the road modules commit must have a Russian label (issue #12 polish).

The API sends *_label fields straight to the UI, and a type the maps do not know falls
back to its raw English name. The roads extend the open "Code" types as their detectors
grow, so instead of a frozen list this test reads the committed analysis/output/ files
and fails on any code (type, level, category, event category) without a label.
"""

import json
from pathlib import Path

from backend.anomalies.services import (
    ANOMALY_TYPE_LABELS,
    CATEGORY_LABELS,
    EVENT_CATEGORY_LABELS,
    LEVEL_LABELS,
    SOURCE_LABELS,
)

OUTPUT = Path(__file__).resolve().parent.parent / "analysis" / "output"

ANOMALY_FIELDS = (
    ("type", ANOMALY_TYPE_LABELS),
    ("level", LEVEL_LABELS),
    ("category", CATEGORY_LABELS),
)


def test_no_committed_code_falls_back_to_its_raw_name():
    checked = 0
    missing = []
    for path in sorted(OUTPUT.glob("*/[ac]*.json")):  # anomalies.json, corporate_anomalies.json
        for item in json.loads(path.read_text("utf-8")):
            checked += 1
            missing += [
                f"{path.parent.name}/{path.name}: {field}={item[field]!r}"
                for field, labels in ANOMALY_FIELDS
                if item[field] not in labels
            ]
    for path in sorted(OUTPUT.glob("*/events.json")):
        for item in json.loads(path.read_text("utf-8")):
            checked += 1
            if item["category"] not in EVENT_CATEGORY_LABELS:
                missing.append(f"{path.parent.name}/events.json: category={item['category']!r}")
    assert checked, "expected committed road outputs to test against"
    assert not missing, f"labels missing for: {', '.join(missing)}"
    # 'ours' and 'corporate' are the only two sources the importer writes
    assert set(SOURCE_LABELS) == {"ours", "corporate"}
