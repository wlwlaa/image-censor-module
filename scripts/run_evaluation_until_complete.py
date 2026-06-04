import argparse
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_DATASET_DIR = Path(r"C:\Users\bulie\Downloads\Telegram Desktop\dataset")


def build_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        "scripts/evaluate_image_pipeline.py",
        "--dataset-dir",
        args.dataset_dir,
        "--output-dir",
        args.output_dir,
        "--repeats",
        str(args.repeats),
        "--pass-k",
        *[str(value) for value in args.pass_k],
        "--transport",
        args.transport,
        "--max-retries",
        str(args.max_retries),
        "--retry-delay-seconds",
        str(args.retry_delay_seconds),
        "--retry-backoff-multiplier",
        str(args.retry_backoff_multiplier),
        "--retry-status-codes",
        *[str(value) for value in args.retry_status_codes],
        "--checkpoint-every",
        str(args.checkpoint_every),
        "--resume",
    ]

    if args.transport == "http":
        command.extend(["--api-url", args.api_url])

    if args.limit is not None:
        command.extend(["--limit", str(args.limit)])

    return command


def run_until_complete(args: argparse.Namespace) -> int:
    command = build_command(args)
    restart_count = 0

    while True:
        print("\nStarting evaluation run")
        print(" ".join(command))
        completed = subprocess.run(command, cwd=PROJECT_ROOT)

        if completed.returncode == 0:
            print("\nEvaluation finished successfully.")
            return 0

        restart_count += 1
        if restart_count > args.max_restarts:
            print(
                f"\nEvaluation failed after {args.max_restarts} restart attempts. "
                f"Last exit code: {completed.returncode}"
            )
            return completed.returncode

        print(
            f"\nEvaluation crashed with exit code {completed.returncode}. "
            f"Restarting from checkpoint in {args.restart_delay_seconds} seconds "
            f"({restart_count}/{args.max_restarts})..."
        )
        time.sleep(args.restart_delay_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run image pipeline evaluation and automatically resume after crashes."
    )
    parser.add_argument("--dataset-dir", default=str(DEFAULT_DATASET_DIR))
    parser.add_argument("--output-dir", default="evaluation_reports")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--pass-k", type=int, nargs="+", default=[1, 2, 3])
    parser.add_argument("--transport", choices=["in-process", "http"], default="http")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--retry-delay-seconds", type=float, default=5.0)
    parser.add_argument("--retry-backoff-multiplier", type=float, default=1.5)
    parser.add_argument(
        "--retry-status-codes",
        type=int,
        nargs="+",
        default=[429, 500, 502, 503, 504],
    )
    parser.add_argument("--max-restarts", type=int, default=100)
    parser.add_argument("--restart-delay-seconds", type=float, default=5.0)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run_until_complete(parse_args()))
