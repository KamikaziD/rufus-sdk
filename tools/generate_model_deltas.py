#!/usr/bin/env python3
"""
Cloud-side utility for generating model delta patches.

This tool generates binary delta patches between model versions,
which can be served to edge devices for bandwidth-efficient updates.

Usage:
    python generate_model_deltas.py \\
        --old-model models/fraud_v1.onnx \\
        --new-model models/fraud_v2.onnx \\
        --output-patch deltas/fraud_v1_to_v2.delta

Requirements:
    pip install bsdiff4

Features:
    - Binary diff using bsdiff algorithm
    - Compression ratio reporting
    - Batch processing for multiple models
    - Hash verification
"""

import argparse
import hashlib
import logging
import os
import sys
from pathlib import Path
from typing import Dict

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ruvon_edge.delta_updates import generate_delta_patch

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def calculate_hash(file_path: str) -> str:
    """Calculate SHA256 hash of file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()


def generate_delta(
    old_model: str,
    new_model: str,
    output_patch: str
) -> Dict[str, any]:
    """
    Generate delta patch and return statistics.

    Returns:
        Dict with compression stats
    """
    if not os.path.exists(old_model):
        logger.error(f"Old model not found: {old_model}")
        return {"success": False, "error": "old_model_not_found"}

    if not os.path.exists(new_model):
        logger.error(f"New model not found: {new_model}")
        return {"success": False, "error": "new_model_not_found"}

    logger.info(f"Generating delta patch...")
    logger.info(f"  Old model: {old_model}")
    logger.info(f"  New model: {new_model}")
    logger.info(f"  Output: {output_patch}")

    # Create output directory if needed
    Path(output_patch).parent.mkdir(parents=True, exist_ok=True)

    # Generate patch
    success = generate_delta_patch(old_model, new_model, output_patch)

    if not success:
        logger.error("Delta generation failed")
        return {"success": False, "error": "generation_failed"}

    # Calculate statistics
    old_size = os.path.getsize(old_model)
    new_size = os.path.getsize(new_model)
    delta_size = os.path.getsize(output_patch)

    bandwidth_saved = new_size - delta_size
    compression_ratio = (delta_size / new_size) * 100 if new_size > 0 else 0

    # Calculate hashes
    old_hash = calculate_hash(old_model)
    new_hash = calculate_hash(new_model)
    delta_hash = calculate_hash(output_patch)

    stats = {
        "success": True,
        "old_model": {
            "path": old_model,
            "size": old_size,
            "hash": old_hash,
        },
        "new_model": {
            "path": new_model,
            "size": new_size,
            "hash": new_hash,
        },
        "delta_patch": {
            "path": output_patch,
            "size": delta_size,
            "hash": delta_hash,
        },
        "bandwidth_saved": bandwidth_saved,
        "bandwidth_saved_pct": (bandwidth_saved / new_size) * 100 if new_size > 0 else 0,
        "compression_ratio": compression_ratio,
    }

    logger.info(f"✓ Delta patch generated successfully")
    logger.info(f"  Old model: {old_size:,} bytes")
    logger.info(f"  New model: {new_size:,} bytes")
    logger.info(f"  Delta size: {delta_size:,} bytes ({compression_ratio:.1f}% of full)")
    logger.info(f"  Bandwidth saved: {bandwidth_saved:,} bytes ({stats['bandwidth_saved_pct']:.1f}%)")
    logger.info(f"  New model hash: sha256:{new_hash}")
    logger.info(f"  Delta hash: sha256:{delta_hash}")

    return stats


def batch_generate(models_dir: str, output_dir: str) -> None:
    """
    Generate delta patches for all model versions in a directory.

    Expects models named like: model_name_v1.onnx, model_name_v2.onnx, etc.
    """
    models_path = Path(models_dir)
    if not models_path.exists():
        logger.error(f"Models directory not found: {models_dir}")
        return

    # Find all model files
    model_files = sorted(models_path.glob("*.onnx")) + sorted(models_path.glob("*.tflite"))

    # Group by base name (without version)
    from collections import defaultdict
    model_groups = defaultdict(list)

    for model_file in model_files:
        # Extract base name and version
        # Example: fraud_detection_v2.onnx -> fraud_detection
        base_name = model_file.stem.rsplit('_v', 1)[0] if '_v' in model_file.stem else model_file.stem
        model_groups[base_name].append(model_file)

    # Generate deltas for each group
    total_stats = []

    for base_name, versions in model_groups.items():
        if len(versions) < 2:
            logger.info(f"Skipping {base_name}: only one version found")
            continue

        logger.info(f"\nProcessing {base_name} ({len(versions)} versions)")

        # Generate deltas between consecutive versions
        for i in range(len(versions) - 1):
            old_model = str(versions[i])
            new_model = str(versions[i + 1])

            output_patch = os.path.join(
                output_dir,
                f"{versions[i].stem}_to_{versions[i + 1].stem}.delta"
            )

            stats = generate_delta(old_model, new_model, output_patch)
            if stats.get("success"):
                total_stats.append(stats)

    # Print summary
    if total_stats:
        total_bandwidth_saved = sum(s["bandwidth_saved"] for s in total_stats)
        avg_compression = sum(s["compression_ratio"] for s in total_stats) / len(total_stats)

        logger.info(f"\n{'='*60}")
        logger.info(f"SUMMARY: Generated {len(total_stats)} delta patches")
        logger.info(f"Total bandwidth saved: {total_bandwidth_saved:,} bytes")
        logger.info(f"Average compression: {avg_compression:.1f}% of full download")
        logger.info(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate binary delta patches for model updates",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single delta patch
  python generate_model_deltas.py \\
      --old-model models/fraud_v1.onnx \\
      --new-model models/fraud_v2.onnx \\
      --output-patch deltas/fraud_v1_to_v2.delta

  # Batch process all models in directory
  python generate_model_deltas.py \\
      --batch \\
      --models-dir models/ \\
      --output-dir deltas/
        """
    )

    parser.add_argument(
        "--old-model",
        help="Path to old model version"
    )
    parser.add_argument(
        "--new-model",
        help="Path to new model version"
    )
    parser.add_argument(
        "--output-patch",
        help="Path to save delta patch"
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Batch process all models in directory"
    )
    parser.add_argument(
        "--models-dir",
        help="Directory containing model files (for batch mode)"
    )
    parser.add_argument(
        "--output-dir",
        help="Directory to save delta patches (for batch mode)"
    )

    args = parser.parse_args()

    # Batch mode
    if args.batch:
        if not args.models_dir or not args.output_dir:
            parser.error("--batch requires --models-dir and --output-dir")
        batch_generate(args.models_dir, args.output_dir)
        return

    # Single delta mode
    if not args.old_model or not args.new_model or not args.output_patch:
        parser.error("Single delta mode requires --old-model, --new-model, and --output-patch")

    stats = generate_delta(args.old_model, args.new_model, args.output_patch)

    if not stats.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
