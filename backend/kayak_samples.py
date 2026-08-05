import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_SAMPLES_DIR = "data/kayak-samples"
_SAMPLES_DIR_ENV = "AIRFARE_KAYAK_SAMPLES_DIR"


def _select_count(body_text: str) -> int:
    from backend.sources.kayak import _RESULT_MARKERS

    return sum(body_text.count(marker) for marker in _RESULT_MARKERS)


def _unique_path(samples_dir: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%f")
    path = samples_dir / f"{stamp}.txt"
    n = 0
    while path.exists():
        n += 1
        path = samples_dir / f"{stamp}-{n}.txt"
    return path


def capture_sample(body_text: str, record: dict, samples_dir) -> Path | None:
    """Persist a rendered Kayak page plus its verdict record.

    Returns the body path, or None if anything went wrong: capture is
    telemetry, not the job, so a search must never fail because a sample
    could not be written (plan 018 task 2.4).
    """
    try:
        directory = Path(samples_dir)
        directory.mkdir(parents=True, exist_ok=True)

        body_path = _unique_path(directory)
        body_path.write_text(body_text)

        sidecar = dict(record)
        sidecar["body_len"] = len(body_text)
        sidecar["select_count"] = _select_count(body_text)
        sidecar["captured_at"] = datetime.now(timezone.utc).isoformat()
        sidecar["sample_path"] = str(body_path)
        body_path.with_suffix(".json").write_text(json.dumps(sidecar, indent=2))

        return body_path
    except Exception as e:
        logger.warning("Kayak sample capture failed: %s: %s", type(e).__name__, e)
        return None
