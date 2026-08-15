"""Plan 019 Phase 3b: offline extraction-model benchmark.

Replays already-captured Kayak bodies from data/kayak-samples/ through each
candidate model. **Zero Kayak requests, zero DB writes, no tracker touched** --
every input is a file that already exists on disk.

    # what the provider actually serves right now (3b.1)
    docker exec airfare-monitor python scripts/kayak_model_benchmark.py list

    # one real call per candidate; a model is only benchmarked if this passes
    docker exec airfare-monitor python scripts/kayak_model_benchmark.py verify \
        --models deepseek-v4-flash-free,mimo-v2.5-free

    # the benchmark itself
    docker exec airfare-monitor python scripts/kayak_model_benchmark.py bench \
        --models a,b,c --runs 10

Calls are issued strictly sequentially: the quantity being measured is a
latency distribution, and running candidates concurrently would queue them
against each other on the same proxy and confound exactly that.
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.fingerprint import make_flight_key  # noqa: E402
from backend.kayak_samples import _DEFAULT_SAMPLES_DIR  # noqa: E402
from backend.sources.kayak import (  # noqa: E402
    _API_KEY_ENV,
    _EXTRACTION_SYSTEM_PROMPT,
    _LLM_BASE_URL,
    KayakSource,
    _results_section,
)

# The five bodies captured by the plan 019 Phase 3 live run (config_id
# "019-phase-3"): the only captured set that is EUR-verified, i.e. the shape
# production actually sees now. All five are distinct pages (distinct md5),
# 20,015-20,257 chars, 51 result markers each.
_DEFAULT_BODIES = (
    "20260805T174756.945533.txt",
    "20260805T175829.973010.txt",
    "20260805T180926.758167.txt",
    "20260805T182027.953238.txt",
    "20260805T183126.174312.txt",
)
_BODY_DEPART_DATE = "2026-10-04"


def _user_message(body_text: str, top_n: int, depart_date: str) -> str:
    """Must stay byte-identical to KayakSource._extract's user message --
    plan 019 Phase 3b forbids touching the prompt, and a benchmark that
    measured a different prompt than production would measure the wrong
    thing. Duplicated rather than imported because _extract builds it inline
    and this phase may not refactor kayak.py."""
    return (
        f"These flights depart on {depart_date}. Use that "
        "date for departure_time, and for arrival_time unless the "
        "itinerary arrives after midnight, which the page marks "
        '"+1".\n\n'
        f"Extract up to {top_n} flights from this Kayak "
        f"results page text:\n\n{_results_section(body_text, top_n)}"
    )


def _client():
    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=os.environ[_API_KEY_ENV], base_url=_LLM_BASE_URL)


async def _call(client, model: str, body_text: str, top_n: int, timeout_s: float) -> dict:
    """One extraction call, shaped exactly like the shipped _extract."""
    started = time.monotonic()
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": _user_message(body_text, top_n, _BODY_DEPART_DATE)},
                ],
                response_format={"type": "json_object"},
                extra_body={"thinking": {"type": "disabled"}},
            ),
            timeout=timeout_s,
        )
    except Exception as e:
        return {
            "latency_s": round(time.monotonic() - started, 2),
            "error": f"{type(e).__name__}: {e}"[:300],
            "content": None,
        }

    usage = getattr(response, "usage", None)
    details = getattr(usage, "completion_tokens_details", None)
    return {
        "latency_s": round(time.monotonic() - started, 2),
        "error": None,
        "content": response.choices[0].message.content,
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "reasoning_tokens": getattr(details, "reasoning_tokens", None),
    }


def _time_grounded(iso_time: str, body_text: str) -> bool:
    """Is this extracted clock time actually printed on the page?

    Not in the plan's 3b.3 list, which asks only that timestamps be
    *canonical* -- but canonical is not correct. Kayak renders the cheapest
    GRU-LIS itinerary as "12:30 am - 5:40 pm", and some candidates read that
    departure as 12:30 (i.e. 12:30 pm). Both parse, both survive
    _canonical_timestamp, both ground their price -- and they are two
    different flight_keys for one physical flight, which is precisely the
    defect plan 019 Phase 2 exists to prevent. So the time gets the same
    treatment as the price: it must appear in the rendered text.
    """
    try:
        parsed = datetime.fromisoformat(iso_time)
    except (TypeError, ValueError):
        return False
    hour12 = parsed.hour % 12 or 12
    return f"{hour12}:{parsed.minute:02d} {'am' if parsed.hour < 12 else 'pm'}" in body_text.lower()


def _keys_time_grounded(flight_keys: list[str], body_text: str) -> bool:
    if not flight_keys:
        return False
    return all(
        _time_grounded(part, body_text)
        for key in flight_keys
        for part in key.split("|")[1:]
    )


def _score(content: str | None, body_text: str, top_n: int) -> dict:
    """Correctness of one response, measured the way the pipeline does it
    (3b.3): parseable, grounded prices, canonical timestamps, single-carrier
    airline, and the flight_keys the row would actually be stored under."""
    if content is None:
        return {"parsed": False}

    try:
        flights = json.loads(content)["flights"]
        if not isinstance(flights, list):
            raise ValueError("'flights' was not a list")
    except Exception as e:
        return {"parsed": False, "parse_error": f"{type(e).__name__}: {e}"[:200]}

    rows = flights[:top_n]
    validated, _rebased_count = KayakSource._validate(rows, body_text)
    mapped = [KayakSource._map_result(r, "EUR", "") for r in validated]

    def _canonical(value) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        try:
            datetime.fromisoformat(text)
            return True
        except ValueError:
            return False

    keys = sorted(make_flight_key(m) for m in mapped)
    return {
        "parsed": True,
        "rows": len(rows),
        "validated_rows": len(validated),
        "all_times_grounded": _keys_time_grounded(keys, body_text),
        "all_grounded": len(rows) > 0 and len(validated) == len(rows),
        "all_timestamps_canonical": len(rows) > 0
        and all(_canonical(r.get("departure_time")) and _canonical(r.get("arrival_time")) for r in rows),
        "single_carrier_airlines": all("," not in m.airline for m in mapped),
        "flight_keys": keys,
        "prices": sorted(m.price for m in mapped),
    }


def _correct(record: dict, top_n: int) -> bool:
    return bool(
        record.get("error") is None
        and record.get("parsed")
        and record.get("rows") == top_n
        and record.get("all_grounded")
        and record.get("all_timestamps_canonical")
        and record.get("all_times_grounded")
        and record.get("single_carrier_airlines")
    )


def _load_bodies(samples_dir: Path, names: list[str]) -> list[tuple[str, str]]:
    bodies = []
    for name in names:
        path = samples_dir / name
        bodies.append((name, path.read_text(encoding="utf-8")))
    return bodies


async def cmd_list(args) -> None:
    client = _client()
    models = await client.models.list()
    for model in models.data:
        print(model.id)


async def cmd_verify(args) -> None:
    """3b.1: confirm each ID with a real call before benchmarking it. A name
    read off a webpage or out of memory is not a verified model id -- plan
    018's rebrowser-playwright and deepseek-v4-flash corrections both came
    from exactly that mistake."""
    client = _client()
    live_ids = {m.id for m in (await client.models.list()).data}
    samples_dir = Path(args.samples_dir)
    name, body = _load_bodies(samples_dir, [args.body])[0]

    for model in args.models:
        listed = model in live_ids
        result = await _call(client, model, body, args.top_n, args.timeout)
        score = _score(result["content"], body, args.top_n)
        verdict = "OK" if _correct({**result, **score}, args.top_n) else "PROBLEM"
        print(
            json.dumps(
                {
                    "model": model,
                    "in_model_list": listed,
                    "verdict": verdict,
                    "latency_s": result["latency_s"],
                    "completion_tokens": result.get("completion_tokens"),
                    "error": result["error"],
                    **{k: v for k, v in score.items() if k not in ("flight_keys", "prices")},
                }
            ),
            flush=True,
        )


async def cmd_bench(args) -> None:
    samples_dir = Path(args.samples_dir)
    bodies = _load_bodies(samples_dir, args.bodies)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out_path = samples_dir / f"model-benchmark-{stamp}.jsonl"
    print(f"writing {out_path}", flush=True)

    client = _client()
    for model in args.models:
        for body_index, (body_name, body_text) in enumerate(bodies):
            for run in range(1, args.runs + 1):
                result = await _call(client, model, body_text, args.top_n, args.timeout)
                score = _score(result.pop("content"), body_text, args.top_n)
                record = {
                    "model": model,
                    "body": body_name,
                    "run": run,
                    "iso_timestamp": datetime.now(timezone.utc).isoformat(),
                    **result,
                    **score,
                }
                record["correct"] = _correct(record, args.top_n)
                with out_path.open("a") as f:
                    f.write(json.dumps(record) + "\n")
                print(
                    f"{model:24s} {body_name[:15]} run{run:3d} "
                    f"{record['latency_s']:7.2f}s tok={record.get('completion_tokens')} "
                    f"rows={record.get('rows')} correct={record['correct']} "
                    f"{record.get('error') or ''}",
                    flush=True,
                )
                await asyncio.sleep(args.gap_seconds)

            # Early abandon (first body only): a candidate that cannot read a
            # page correctly half the time is not a candidate, and spending
            # the other four bodies on it just delays the ones that are.
            if body_index == 0 and args.runs >= 4:
                first = _records(out_path, model, samples_dir, args.top_n)
                if sum(r["correct"] for r in first) / len(first) < args.abandon_below:
                    print(f"ABANDON {model}: {sum(r['correct'] for r in first)}/{len(first)} correct on body 1", flush=True)
                    break

    _summarize(out_path, args.top_n, samples_dir)


def _records(path: Path, model: str | None = None, samples_dir: Path | None = None, top_n: int = 5) -> list[dict]:
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if samples_dir is not None:
        # Re-score rather than trust the stored verdict: _time_grounded was
        # added after the first benchmark run, and every model has to be
        # judged on the same rule for the table to mean anything.
        for record in records:
            body = (samples_dir / record["body"]).read_text(encoding="utf-8")
            record["all_times_grounded"] = _keys_time_grounded(record.get("flight_keys") or [], body)
            record["correct"] = _correct(record, top_n)
    return [r for r in records if model is None or r["model"] == model]


def _summarize(path: Path, top_n: int, samples_dir: Path) -> None:
    records = _records(path, samples_dir=samples_dir, top_n=top_n)
    models = list(dict.fromkeys(r["model"] for r in records))
    print("\n| model | runs | correct | p50 s | p90 s | max s | fits 30s | completion tok p50/max | key determinism |")
    print("|---|---|---|---|---|---|---|---|---|")
    for model in models:
        rows = [r for r in records if r["model"] == model]
        lat = sorted(r["latency_s"] for r in rows)
        correct = [r for r in rows if r["correct"]]
        toks = sorted(r["completion_tokens"] for r in rows if r.get("completion_tokens") is not None)
        fits = sum(1 for r in rows if r["latency_s"] <= 30.0 and r["correct"])

        # Determinism: per body, the share of runs landing on the modal key
        # set. A model that reads the same page two different ways forks one
        # flight's history the same way the flight_number placeholders did.
        shares = []
        for body in dict.fromkeys(r["body"] for r in rows):
            keysets = [tuple(r["flight_keys"]) for r in rows if r["body"] == body and r.get("flight_keys")]
            if keysets:
                shares.append(max(keysets.count(k) for k in set(keysets)) / len(keysets))
        determinism = f"{statistics.mean(shares):.0%}" if shares else "n/a"

        def q(values, p):
            return values[min(len(values) - 1, int(p * len(values)))] if values else float("nan")

        print(
            f"| `{model}` | {len(rows)} | {len(correct)}/{len(rows)} | {q(lat, 0.5):.1f} | "
            f"{q(lat, 0.9):.1f} | {max(lat):.1f} | {fits}/{len(rows)} | "
            f"{q(toks, 0.5) if toks else 'n/a'}/{max(toks) if toks else 'n/a'} | {determinism} |"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["list", "verify", "bench", "summarize"])
    parser.add_argument("--models", default="", help="comma-separated model ids")
    parser.add_argument("--bodies", default=",".join(_DEFAULT_BODIES))
    parser.add_argument("--body", default=_DEFAULT_BODIES[0], help="verify mode: single body")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=120.0, help="hard cap per call; deliberately far above the shipped 30s so the tail is measured rather than truncated")
    parser.add_argument("--gap-seconds", type=float, default=1.0)
    parser.add_argument("--abandon-below", type=float, default=0.5)
    parser.add_argument("--samples-dir", default=_DEFAULT_SAMPLES_DIR)
    parser.add_argument("--jsonl", help="summarize mode: path to a benchmark jsonl")
    args = parser.parse_args()
    args.models = [m.strip() for m in args.models.split(",") if m.strip()]
    args.bodies = [b.strip() for b in args.bodies.split(",") if b.strip()]

    if args.mode == "summarize":
        _summarize(Path(args.jsonl), args.top_n, Path(args.samples_dir))
        return
    asyncio.run({"list": cmd_list, "verify": cmd_verify, "bench": cmd_bench}[args.mode](args))


if __name__ == "__main__":
    main()
