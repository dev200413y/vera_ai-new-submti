"""
generate_submission.py — Generate submission.jsonl from the real dataset.

This script:
  1. Loads the real expanded dataset (dataset/*)
  2. Loads test_pairs.json (the 30 canonical pairs all candidates must compose)
  3. Calls compose() for each pair
  4. Writes submission.jsonl (30 lines, one per test pair)

Usage:
    export MISTRAL_API_KEY=your_key_here
    python generate_submission.py

Output:
    submission.jsonl  (submit this to the challenge portal)
"""

import json
import time
from pathlib import Path

from composer import compose


# ── Paths ─────────────────────────────────────────────────────────────────────

DATASET_DIR = Path("dataset")
OUT_FILE    = "submission.jsonl"


# ── Loaders ───────────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [WARN] Could not load {path}: {e}")
        return {}


def load_folder(folder: Path, id_field: str) -> dict:
    """Load all JSON files in a folder into a dict keyed by id_field."""
    result = {}
    if not folder.exists():
        return result
    for f in sorted(folder.glob("*.json")):
        data = load_json(f)
        if data:
            key = data.get(id_field) or data.get("slug") or f.stem
            result[key] = data
    return result


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("━" * 60)
    print("  Vera Challenger — Submission Generator")
    print("━" * 60)

    # Load dataset
    print("\nLoading dataset...")
    categories = load_folder(DATASET_DIR / "categories", "slug")
    merchants  = load_folder(DATASET_DIR / "merchants",  "merchant_id")
    customers  = load_folder(DATASET_DIR / "customers",  "customer_id")
    triggers   = load_folder(DATASET_DIR / "triggers",   "id")

    print(f"  ✅ {len(categories)} categories | {len(merchants)} merchants | "
          f"{len(customers)} customers | {len(triggers)} triggers")

    # Load canonical 30 test pairs
    test_pairs_file = DATASET_DIR / "test_pairs.json"
    if not test_pairs_file.exists():
        print(f"\n  ❌ test_pairs.json not found at {test_pairs_file}")
        print("     Run: python dataset/generate_dataset.py --out dataset/")
        return

    test_pairs = json.loads(test_pairs_file.read_text())["pairs"]
    print(f"  ✅ {len(test_pairs)} canonical test pairs loaded")

    # Compose
    print(f"\nComposing {len(test_pairs)} messages...\n" + "─" * 60)
    results = []
    errors  = 0

    for pair in test_pairs:
        test_id     = pair["test_id"]
        trigger_id  = pair["trigger_id"]
        merchant_id = pair["merchant_id"]
        customer_id = pair.get("customer_id")

        # Load the 4 contexts for this pair
        trg = triggers.get(trigger_id)
        if not trg:
            print(f"  ❌ {test_id}: trigger not found: {trigger_id}")
            errors += 1
            continue

        merch = merchants.get(merchant_id)
        if not merch:
            print(f"  ❌ {test_id}: merchant not found: {merchant_id}")
            errors += 1
            continue

        cat = categories.get(merch.get("category_slug", ""))
        if not cat:
            print(f"  ❌ {test_id}: category not found for merchant {merchant_id}")
            errors += 1
            continue

        cust = customers.get(customer_id) if customer_id else None

        # Compose
        t0 = time.time()
        try:
            result = compose(cat, merch, trg, cust)
        except Exception as e:
            print(f"  ❌ {test_id}: compose() raised {e}")
            result = {
                "body":            f"[ERROR: {e}]",
                "cta":             "open_ended",
                "send_as":         "vera",
                "suppression_key": "",
                "rationale":       str(e),
            }
            errors += 1

        elapsed = time.time() - t0

        # Validation
        body = result.get("body", "")
        warnings = []
        if len(body) > 320:
            warnings.append(f"BODY_TOO_LONG ({len(body)}c)")
        if "http" in body.lower():
            warnings.append("HAS_URL")
        if not body or body.startswith("[ERROR"):
            warnings.append("EMPTY_OR_ERROR")

        # Print summary line
        icon = "✅" if not warnings else "⚠️ "
        warn_str = f"  [{' '.join(warnings)}]" if warnings else ""
        kind = trg.get("kind", "?")
        print(f"  {icon} {test_id} | {kind:<26} | {len(body):>3}c | {elapsed:.1f}s{warn_str}")
        print(f"     {body[:90]}{'...' if len(body) > 90 else ''}")
        print()

        # Build JSONL line
        results.append({
            "test_id":        test_id,
            "trigger_id":     trigger_id,
            "merchant_id":    merchant_id,
            "customer_id":    customer_id,
            "kind":           kind,
            "body":           body[:320],
            "cta":            result.get("cta", "open_ended"),
            "send_as":        result.get("send_as", "vera"),
            "suppression_key": result.get("suppression_key", ""),
            "rationale":      result.get("rationale", ""),
        })

    # Write output
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        for line in results:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    ok = len(results) - errors
    print("─" * 60)
    print(f"\n  ✅ Done! {ok}/{len(results)} successful")
    print(f"  📄 Output: {OUT_FILE}")
    print(f"  ❌ Errors: {errors}")
    if errors == 0:
        print("\n  Ready to submit! 🚀")


if __name__ == "__main__":
    main()
