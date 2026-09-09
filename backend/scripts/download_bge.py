"""Download the Chinese BGE embedding model from ModelScope.

Usage:
    python scripts/download_bge.py --output ./models/bge-small-zh-v1.5

The model files are intentionally kept outside git. Set BGE_MODEL_PATH to the
resulting directory before starting the backend.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        default="AI-ModelScope/bge-small-zh-v1.5",
        help="ModelScope model id",
    )
    parser.add_argument(
        "--output",
        default="./models/bge-small-zh-v1.5",
        help="Local model directory",
    )
    args = parser.parse_args()

    try:
        from modelscope import snapshot_download
    except ImportError as exc:
        raise SystemExit(
            "请先安装 ModelScope：pip install -r requirements-bge.txt"
        ) from exc

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    model_path = snapshot_download(args.model, cache_dir=str(output.parent))
    print(f"Model downloaded to: {model_path}")
    print(f"Set BGE_MODEL_PATH={model_path}")


if __name__ == "__main__":
    main()
