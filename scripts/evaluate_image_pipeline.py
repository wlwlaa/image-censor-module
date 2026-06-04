import argparse
import csv
import json
import mimetypes
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

IMAGE_EXTENSIONS = {
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}
TARGET_LABELS = {"safe", "unsafe"}
DEFAULT_DATASET_DIR = Path(r"C:\Users\bulie\Downloads\Telegram Desktop\dataset")
DEFAULT_OUTPUT_DIR = Path("evaluation_reports")
DEFAULT_PASS_K = [1, 2, 3]
DEFAULT_CHECKPOINT_EVERY = 25
DEFAULT_RETRY_STATUS_CODES = [429, 500, 502, 503, 504]
CHECKPOINT_PREDICTIONS_FILENAME = "predictions_latest.csv"
CHECKPOINT_METRICS_FILENAME = "metrics_latest.json"


def discover_dataset(dataset_dir: Path) -> list[dict[str, str]]:
    samples: list[dict[str, str]] = []

    for category_dir in sorted(dataset_dir.iterdir()):
        if not category_dir.is_dir() or category_dir.name.startswith("__"):
            continue

        for target in sorted(TARGET_LABELS):
            target_dir = category_dir / target
            if not target_dir.is_dir():
                continue

            for image_path in sorted(target_dir.rglob("*")):
                if image_path.is_file() and image_path.suffix.lower() in IMAGE_EXTENSIONS:
                    samples.append(
                        {
                            "category": category_dir.name,
                            "target": target,
                            "path": str(image_path),
                        }
                    )

    return samples


def _extract_llama_guard(response_json: dict[str, Any]) -> dict[str, Any] | None:
    if "llama_guard" in response_json:
        return response_json.get("llama_guard")

    analysis = response_json.get("analysis") or {}
    return analysis.get("llama_guard")


def prediction_from_response(response_json: dict[str, Any]) -> str:
    if "llama_guard" in response_json and "analysis" not in response_json:
        llama_guard = response_json.get("llama_guard") or {}
        return "safe" if llama_guard.get("is_safe") is True else "unsafe"

    return "safe" if response_json.get("status") == "success" else "unsafe"


def _truncate_text(value: Any, max_length: int = 1000) -> str | None:
    if value is None:
        return None

    text = str(value)
    if len(text) <= max_length:
        return text

    return text[: max_length - 3] + "..."


def summarize_failure(
    status_code: int | None,
    response_json: dict[str, Any],
    api_error: Any = None,
) -> tuple[str | None, str | None]:
    if api_error:
        if isinstance(api_error, dict):
            error_type = api_error.get("type") or "request_error"
            message = api_error.get("message") or api_error
            return str(error_type), _truncate_text(message)

        return "request_error", _truncate_text(api_error)

    if status_code is not None and status_code >= 500:
        return "server_error", _truncate_text(response_json)

    if status_code == 429:
        return "rate_limited", _truncate_text(response_json)

    if status_code is not None and status_code >= 400:
        return "http_error", _truncate_text(response_json)

    if response_json.get("status") == "error":
        return str(response_json.get("reason") or "pipeline_error"), _truncate_text(
            response_json.get("message") or response_json
        )

    analysis = response_json.get("analysis") or {}
    llama_guard = response_json.get("llama_guard") or analysis.get("llama_guard") or {}
    if llama_guard.get("verdict") == "error":
        return "llama_guard_failed", _truncate_text(llama_guard.get("reason"))

    return None, None


def call_image_endpoint(
    client: Any,
    endpoint_url: str,
    image_path: Path,
    max_retries: int = 2,
    retry_delay_seconds: float = 2.0,
    retry_backoff_multiplier: float = 1.5,
    retry_status_codes: set[int] | None = None,
) -> dict[str, Any]:
    mime_type = mimetypes.guess_type(str(image_path))[0] or "application/octet-stream"
    retry_status_codes = retry_status_codes or set(DEFAULT_RETRY_STATUS_CODES)
    last_response = None

    for retry_index in range(max_retries + 1):
        try:
            with image_path.open("rb") as image_file:
                response = client.post(
                    endpoint_url,
                    files={"file": (image_path.name, image_file, mime_type)},
                )
            last_response = response
            if response.status_code not in retry_status_codes:
                break

            if retry_index < max_retries:
                delay = retry_delay_seconds * (retry_backoff_multiplier**retry_index)
                print(
                    f"Retryable HTTP {response.status_code}; retrying in {delay:.1f}s "
                    f"({retry_index + 1}/{max_retries})"
                )
                time.sleep(delay)
                continue

            break
        except Exception as exc:
            if retry_index < max_retries:
                delay = retry_delay_seconds * (retry_backoff_multiplier**retry_index)
                print(
                    f"Request failed: {exc}; retrying in {delay:.1f}s "
                    f"({retry_index + 1}/{max_retries})"
                )
                time.sleep(delay)
                continue

            return {
                "predicted": "unsafe",
                "status_code": None,
                "api_error": {
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                },
                "response": {
                    "status": "error",
                    "reason": "request_failed",
                    "message": f"Pipeline request failed: {exc}",
                },
            }

    response = last_response

    try:
        response_json = response.json()
    except ValueError:
        response_json = {"raw_response": response.text}

    if response.status_code >= 400:
        return {
            "predicted": "unsafe",
            "status_code": response.status_code,
            "api_error": response_json,
            "response": response_json,
        }

    return {
        "predicted": prediction_from_response(response_json),
        "status_code": response.status_code,
        "api_error": None,
        "response": response_json,
    }


def _recall(correct: int, total: int) -> float | None:
    if total == 0:
        return None
    return correct / total


def _is_technical_failure(row: dict[str, Any]) -> bool:
    status_code = row.get("status_code")
    status = row.get("status")
    api_error = row.get("api_error")

    if status == "error":
        return True
    if api_error:
        return True
    if status_code is None:
        return True
    return int(status_code) >= 500


def compute_metrics(
    samples: list[dict[str, str]],
    attempt_rows: list[dict[str, Any]],
    pass_ks: list[int],
) -> dict[str, Any]:
    first_attempts = [row for row in attempt_rows if row["attempt"] == 1]
    valid_first_attempts = [row for row in first_attempts if not _is_technical_failure(row)]
    total = len(first_attempts)
    correct = sum(1 for row in first_attempts if row["is_correct"])
    valid_total = len(valid_first_attempts)
    valid_correct = sum(1 for row in valid_first_attempts if row["is_correct"])
    technical_failures = total - valid_total
    technical_failure_types: dict[str, int] = defaultdict(int)
    for row in first_attempts:
        if _is_technical_failure(row):
            failure_type = row.get("failure_type") or "unknown"
            technical_failure_types[str(failure_type)] += 1

    by_label: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})
    by_category: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})
    by_category_label: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"total": 0, "correct": 0})
    )

    for row in first_attempts:
        target = row["target"]
        category = row["category"]
        by_label[target]["total"] += 1
        by_category[category]["total"] += 1
        by_category_label[category][target]["total"] += 1

        if row["is_correct"]:
            by_label[target]["correct"] += 1
            by_category[category]["correct"] += 1
            by_category_label[category][target]["correct"] += 1

    valid_by_label: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})
    valid_by_category: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})

    for row in valid_first_attempts:
        target = row["target"]
        category = row["category"]
        valid_by_label[target]["total"] += 1
        valid_by_category[category]["total"] += 1
        if row["is_correct"]:
            valid_by_label[target]["correct"] += 1
            valid_by_category[category]["correct"] += 1

    sample_attempts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in attempt_rows:
        sample_attempts[row["sample_id"]].append(row)

    max_attempts = max((len(rows) for rows in sample_attempts.values()), default=0)

    unsafe_sample_ids = {
        f"{sample['category']}::{sample['target']}::{sample['path']}"
        for sample in samples
        if sample["target"] == "unsafe"
    }

    unsafe_by_category: dict[str, set[str]] = defaultdict(set)
    for sample in samples:
        if sample["target"] == "unsafe":
            sample_id = f"{sample['category']}::{sample['target']}::{sample['path']}"
            unsafe_by_category[sample["category"]].add(sample_id)

    pass_at_k: dict[str, Any] = {}
    pass_at_k_by_category: dict[str, dict[str, float | None]] = {}

    for k in pass_ks:
        if k > max_attempts:
            pass_at_k[str(k)] = None
            pass_at_k_by_category[str(k)] = {
                category: None for category in sorted(unsafe_by_category)
            }
            continue

        if not unsafe_sample_ids:
            pass_at_k[str(k)] = None
        else:
            bypassed = sum(
                1
                for sample_id in unsafe_sample_ids
                if any(row["predicted"] == "safe" for row in sample_attempts[sample_id][:k])
            )
            pass_at_k[str(k)] = bypassed / len(unsafe_sample_ids)

        category_scores: dict[str, float | None] = {}
        for category, sample_ids in sorted(unsafe_by_category.items()):
            if not sample_ids:
                category_scores[category] = None
                continue

            bypassed = sum(
                1
                for sample_id in sample_ids
                if any(row["predicted"] == "safe" for row in sample_attempts[sample_id][:k])
            )
            category_scores[category] = bypassed / len(sample_ids)

        pass_at_k_by_category[str(k)] = category_scores

    return {
        "total_samples": len(samples),
        "evaluated_first_attempts": total,
        "technical_failures_first_attempt": technical_failures,
        "technical_failure_rate_first_attempt": _recall(technical_failures, total),
        "technical_failure_types_first_attempt": dict(
            sorted(technical_failure_types.items())
        ),
        "overall_recall": _recall(correct, total),
        "valid_first_attempts": valid_total,
        "valid_overall_recall_excluding_technical_failures": _recall(
            valid_correct, valid_total
        ),
        "per_target_recall": {
            label: {
                "recall": _recall(values["correct"], values["total"]),
                "correct": values["correct"],
                "total": values["total"],
            }
            for label, values in sorted(by_label.items())
        },
        "valid_per_target_recall_excluding_technical_failures": {
            label: {
                "recall": _recall(values["correct"], values["total"]),
                "correct": values["correct"],
                "total": values["total"],
            }
            for label, values in sorted(valid_by_label.items())
        },
        "per_category_recall": {
            category: {
                "recall": _recall(values["correct"], values["total"]),
                "correct": values["correct"],
                "total": values["total"],
            }
            for category, values in sorted(by_category.items())
        },
        "valid_per_category_recall_excluding_technical_failures": {
            category: {
                "recall": _recall(values["correct"], values["total"]),
                "correct": values["correct"],
                "total": values["total"],
            }
            for category, values in sorted(valid_by_category.items())
        },
        "per_category_target_recall": {
            category: {
                label: {
                    "recall": _recall(values["correct"], values["total"]),
                    "correct": values["correct"],
                    "total": values["total"],
                }
                for label, values in sorted(label_values.items())
            }
            for category, label_values in sorted(by_category_label.items())
        },
        "pass_at_k_unsafe": pass_at_k,
        "pass_at_k_unsafe_by_category": pass_at_k_by_category,
    }


def write_predictions_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "sample_id",
        "category",
        "target",
        "path",
        "attempt",
        "predicted",
        "is_correct",
        "status_code",
        "status",
        "reason",
        "message",
        "failure_type",
        "failure_detail",
        "llama_verdict",
        "llama_reason",
        "api_error",
    ]

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})


def load_existing_predictions(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    with path.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        rows = list(reader)

    for row in rows:
        row["attempt"] = int(row["attempt"])
        row["is_correct"] = str(row["is_correct"]).lower() == "true"
        if row.get("status_code"):
            row["status_code"] = int(row["status_code"])
        else:
            row["status_code"] = None

    return rows


def discard_technical_failures(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if not _is_technical_failure(row)]


def completed_attempt_keys(rows: list[dict[str, Any]]) -> set[tuple[str, int]]:
    return {(row["sample_id"], int(row["attempt"])) for row in rows}


def write_metrics_json(
    path: Path,
    samples: list[dict[str, str]],
    attempt_rows: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    metrics = compute_metrics(samples, attempt_rows, args.pass_k)
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "dataset_dir": str(Path(args.dataset_dir)),
        "api_url": args.api_url,
        "endpoint": args.endpoint,
        "transport": args.transport,
        "repeats": args.repeats,
        "pass_k": args.pass_k,
        "metrics": metrics,
    }
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    dataset_dir = Path(args.dataset_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = discover_dataset(dataset_dir)
    if args.limit:
        samples = samples[: args.limit]

    if args.transport == "in-process":
        endpoint_url = args.endpoint
    else:
        endpoint_url = args.api_url.rstrip("/") + args.endpoint

    checkpoint_predictions_path = output_dir / CHECKPOINT_PREDICTIONS_FILENAME
    checkpoint_metrics_path = output_dir / CHECKPOINT_METRICS_FILENAME

    attempt_rows = load_existing_predictions(checkpoint_predictions_path) if args.resume else []
    if args.resume and attempt_rows and args.retry_technical_failures_on_resume:
        original_count = len(attempt_rows)
        attempt_rows = discard_technical_failures(attempt_rows)
        discarded_count = original_count - len(attempt_rows)
        if discarded_count:
            print(
                f"Discarded {discarded_count} technical failure rows from checkpoint; "
                "they will be retried."
            )
    done_keys = completed_attempt_keys(attempt_rows)

    if attempt_rows:
        print(f"Loaded {len(attempt_rows)} existing attempt rows from {checkpoint_predictions_path}")

    if args.transport == "in-process":
        from fastapi.testclient import TestClient

        from app.main import app

        client: Any = TestClient(app, raise_server_exceptions=False)
        print("Using in-process FastAPI transport. Uvicorn server is not required.")
    else:
        client = httpx.Client(timeout=args.timeout_seconds)
        print(f"Using HTTP transport: {endpoint_url}")

    try:
        for index, sample in enumerate(samples, start=1):
            image_path = Path(sample["path"])
            sample_id = f"{sample['category']}::{sample['target']}::{sample['path']}"

            print(
                f"[{index}/{len(samples)}] {sample['category']} / {sample['target']} / {image_path.name}"
            )

            for attempt in range(1, args.repeats + 1):
                if (sample_id, attempt) in done_keys:
                    continue

                result = call_image_endpoint(
                    client,
                    endpoint_url,
                    image_path,
                    max_retries=args.max_retries,
                    retry_delay_seconds=args.retry_delay_seconds,
                    retry_backoff_multiplier=args.retry_backoff_multiplier,
                    retry_status_codes=set(args.retry_status_codes),
                )
                response_json = result["response"]
                llama_guard = _extract_llama_guard(response_json) or {}
                failure_type, failure_detail = summarize_failure(
                    status_code=result["status_code"],
                    response_json=response_json,
                    api_error=result["api_error"],
                )

                attempt_rows.append(
                    {
                        "sample_id": sample_id,
                        "category": sample["category"],
                        "target": sample["target"],
                        "path": sample["path"],
                        "attempt": attempt,
                        "predicted": result["predicted"],
                        "is_correct": result["predicted"] == sample["target"],
                        "status_code": result["status_code"],
                        "status": response_json.get("status"),
                        "reason": response_json.get("reason"),
                        "message": response_json.get("message"),
                        "failure_type": failure_type,
                        "failure_detail": failure_detail,
                        "llama_verdict": llama_guard.get("verdict"),
                        "llama_reason": llama_guard.get("reason"),
                        "api_error": json.dumps(result["api_error"], ensure_ascii=False)
                        if result["api_error"]
                        else None,
                    }
                )
                done_keys.add((sample_id, attempt))

            if index % args.checkpoint_every == 0:
                write_predictions_csv(checkpoint_predictions_path, attempt_rows)
                write_metrics_json(checkpoint_metrics_path, samples, attempt_rows, args)

        write_predictions_csv(checkpoint_predictions_path, attempt_rows)
        write_metrics_json(checkpoint_metrics_path, samples, attempt_rows, args)
    finally:
        client.close()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    metrics_path = output_dir / f"metrics_{timestamp}.json"
    predictions_path = output_dir / f"predictions_{timestamp}.csv"

    report = write_metrics_json(metrics_path, samples, attempt_rows, args)
    write_predictions_csv(predictions_path, attempt_rows)

    print("\nEvaluation complete")
    print(f"Metrics: {metrics_path}")
    print(f"Predictions: {predictions_path}")
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))

    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate image moderation pipeline metrics.")
    parser.add_argument("--dataset-dir", default=str(DEFAULT_DATASET_DIR))
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--endpoint", default="/upload-image")
    parser.add_argument("--transport", choices=["in-process", "http"], default="http")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--pass-k", type=int, nargs="+", default=DEFAULT_PASS_K)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--retry-delay-seconds", type=float, default=5.0)
    parser.add_argument("--retry-backoff-multiplier", type=float, default=1.5)
    parser.add_argument(
        "--retry-status-codes",
        type=int,
        nargs="+",
        default=DEFAULT_RETRY_STATUS_CODES,
    )
    parser.add_argument(
        "--retry-technical-failures-on-resume",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--checkpoint-every", type=int, default=DEFAULT_CHECKPOINT_EVERY)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    evaluate(parse_args())
