"""Plan 018 Phase 3 runner: N Kayak attempts at a fixed spacing, one sample per
attempt.

Writes only to data/kayak-samples/ -- never touches the database or any
tracker. Use a throwaway route (Phase 3 Decision 6): a tracked route would
have its price history and its reputation polluted by the experiment.

    docker exec airfare-monitor python scripts/kayak_experiment.py \
        --attempts 10 --spacing-minutes 10 --origin GRU --dest LIS \
        --date 2026-10-04 --config-id c1-c4

Detach it (~100 min for the default run) and tail the JSONL as it goes.
"""

import argparse
import asyncio
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.fingerprint import make_flight_key  # noqa: E402
from backend.kayak_samples import _DEFAULT_SAMPLES_DIR  # noqa: E402
from backend.sources.kayak import KayakRenderConfig, KayakSource  # noqa: E402

# Fields the source records on the sidecar but does not expose on itself.
# Copied into the JSONL so the run is analysable from one file -- joining
# sidecars back in after the fact silently omits any attempt whose capture
# failed (plan 018 attempt 7).
_SIDECAR_FIELDS = (
    "blocked_by_markers",
    "blocked_by_structure",
    "extracted_rows",
    "validated_rows",
    "outcome",
    "body_len",
    "select_count",
)


def _egress_ip() -> str:
    """If the VPN drops mid-run the arm silently changes meaning, and this is
    the only way to notice after the fact (Phase 3)."""
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=10) as response:
            return response.read().decode().strip()
    except Exception as e:
        return f"unknown ({type(e).__name__})"


def _sidecar_fields(sample_path) -> dict:
    if not sample_path:
        return {}
    try:
        sidecar = json.loads(Path(sample_path).with_suffix(".json").read_text())
    except Exception:
        return {}
    return {k: sidecar[k] for k in _SIDECAR_FIELDS if k in sidecar}


async def _attempt(n: int, args, samples_dir: str) -> dict:
    config = KayakRenderConfig(config_id=args.config_id, samples_dir=samples_dir)
    source = KayakSource(config=config)
    source.sample_context = {"attempt_n": n, "egress_ip": _egress_ip()}

    started = datetime.now(timezone.utc)
    results = await source.search(args.origin, args.dest, args.date, None, args.currency, args.top_n)
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()

    record = {
        "attempt_n": n,
        "iso_timestamp": started.isoformat(),
        "egress_ip": source.sample_context["egress_ip"],
        "config_id": args.config_id,
        "returned_rows": len(results),
        "flight_keys": [make_flight_key(r) for r in results],
        "prices": [r.price for r in results],
        "last_error": source.last_error,
        "last_error_level": source.last_error_level,
        "sample_path": str(source.last_sample_path) if source.last_sample_path else None,
        "elapsed_s": round(elapsed, 2),
    }
    record.update(_sidecar_fields(source.last_sample_path))
    return record


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempts", type=int, default=10)
    parser.add_argument("--spacing-minutes", type=float, default=10.0)
    parser.add_argument("--origin", default="GRU")
    parser.add_argument("--dest", default="LIS")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD, ~60 days out")
    parser.add_argument("--currency", default="EUR")
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--config-id", default="c1-c4")
    parser.add_argument("--samples-dir", default=_DEFAULT_SAMPLES_DIR)
    args = parser.parse_args()

    samples_dir = Path(args.samples_dir)
    samples_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    results_path = samples_dir / f"experiment-{args.config_id}-{stamp}.jsonl"

    print(f"writing {results_path}", flush=True)

    for n in range(1, args.attempts + 1):
        record = await _attempt(n, args, str(samples_dir))
        # Append per attempt so a crash keeps everything collected so far.
        with results_path.open("a") as f:
            f.write(json.dumps(record) + "\n")
        print(json.dumps(record), flush=True)

        if n < args.attempts:
            await asyncio.sleep(args.spacing_minutes * 60)


if __name__ == "__main__":
    asyncio.run(main())
