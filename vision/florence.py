# vision/florence.py
"""
Florence-2 OCR and captioning module.

Provides two capabilities that CLIP Interrogator lacks:
1. OCR with spatial awareness - reads text IN images (meme labels, signs, etc.)
2. Detailed captioning - understands scene composition and relationships

Uses singleton pattern matching interrogator.py - model loads once on first use,
runs synchronously in thread pool to avoid blocking the event loop.

Usage:
    from vision.florence import get_florence, analyze_image

    # Async (preferred - non-blocking)
    results = await analyze_image("/path/to/image.png")
    # results = {"ocr": "cleaned text...", "caption": "scene description..."}

    # Direct singleton access
    florence = get_florence()
    results = await florence.analyze("/path/to/image.png")
"""

import asyncio
import logging
import re
from typing import Optional

logger = logging.getLogger("Vision.Florence")


class FlorenceAnalyzer:
    """
    Florence-2 wrapper for OCR and detailed captioning.
    Singleton pattern - loads model once, reuses for all images.
    Mirrors ImageInterrogator's architecture for consistency.
    """
    _instance = None
    _model = None
    _processor = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _ensure_loaded(self):
        """
        Lazy load Florence-2 model on first use.
        Requires CUDA GPU - loads in float16 for memory efficiency.
        """
        if self._model is not None:
            return

        logger.info("Loading Florence-2-large model (first use)...")
        try:
            from transformers import AutoProcessor, AutoModelForCausalLM
            import torch

            self._model = AutoModelForCausalLM.from_pretrained(
                "microsoft/Florence-2-large",
                torch_dtype=torch.float16,
                trust_remote_code=True
            ).cuda()

            self._processor = AutoProcessor.from_pretrained(
                "microsoft/Florence-2-large",
                trust_remote_code=True
            )

            logger.info("Florence-2-large loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load Florence-2: {e}")
            raise

    def _run_task(self, image, prompt: str, max_tokens: int = 256) -> str:
        """
        Run a single Florence-2 task (OCR or captioning) synchronously.

        Args:
            image: PIL Image object (already loaded and converted to RGB)
            prompt: Florence task prompt (e.g. "<OCR_WITH_REGION>")
            max_tokens: Maximum tokens to generate

        Returns:
            Raw model output string (needs parsing by caller)
        """
        import torch

        inputs = self._processor(
            text=prompt, images=image, return_tensors="pt"
        ).to("cuda", torch.float16)

        generated = self._model.generate(**inputs, max_new_tokens=max_tokens)
        result = self._processor.batch_decode(generated, skip_special_tokens=False)[0]
        return result

    def analyze_sync(self, image_path: str) -> dict:
        """
        Run both OCR and captioning synchronously.
        Call via asyncio.to_thread() to avoid blocking.

        Returns dict with raw 'ocr' and 'caption' strings.
        These still contain <loc_XXX> tags and XML artifacts --
        use vision.parsing to clean them.
        """
        from PIL import Image

        self._ensure_loaded()
        image = Image.open(image_path).convert("RGB")

        results = {}

        # Task 1: OCR with bounding box regions
        # Returns text found in image with spatial location tags
        # e.g. "POP!<loc_230><loc_147>TRANNERLAND<loc_470><loc_176>"
        try:
            results["ocr"] = self._run_task(image, "<OCR_WITH_REGION>")
        except Exception as e:
            logger.warning(f"Florence OCR failed: {e}")
            results["ocr"] = ""

        # Task 2: Detailed scene caption
        # Returns verbose natural language description of the full image
        # e.g. "The image is of a Funko Pop! Boboli vinyl figure..."
        try:
            results["caption"] = self._run_task(
                image, "<MORE_DETAILED_CAPTION>", max_tokens=300
            )
        except Exception as e:
            logger.warning(f"Florence captioning failed: {e}")
            results["caption"] = ""

        return results

    async def analyze(self, image_path: str) -> dict:
        """
        Async wrapper - runs in thread pool to not block event loop.
        Returns dict with raw 'ocr' and 'caption' strings.
        """
        return await asyncio.to_thread(self.analyze_sync, image_path)


# ============== MODULE-LEVEL SINGLETON ==============

_florence: Optional[FlorenceAnalyzer] = None


def get_florence() -> FlorenceAnalyzer:
    """Get or create the singleton Florence analyzer."""
    global _florence
    if _florence is None:
        _florence = FlorenceAnalyzer()
    return _florence


async def analyze_image(image_path: str) -> dict:
    """
    Main async entry point for Florence-2 analysis.

    Returns dict with raw 'ocr' and 'caption' strings.
    Use vision.parsing.parse_florence_ocr() and parse_florence_caption()
    to clean the outputs.
    """
    return await get_florence().analyze(image_path)


# ============== STANDALONE CLI ==============

def main():
    """CLI entry point for testing Florence-2 on images."""
    import argparse
    import json
    import sys
    import time
    from pathlib import Path

    # Import parsing utilities for clean display
    from vision.parsing import parse_florence_ocr, extract_meaningful_ocr, parse_florence_caption

    parser = argparse.ArgumentParser(description="Test Florence-2 image analysis")
    parser.add_argument("image", help="Path to image file")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show timing and raw output")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--raw", action="store_true", help="Show raw model output (no parsing)")
    args = parser.parse_args()

    if not Path(args.image).is_file():
        print(f"Error: {args.image} not found", file=sys.stderr)
        sys.exit(1)

    start = time.time()
    florence = get_florence()
    results = florence.analyze_sync(args.image)
    elapsed = time.time() - start

    if args.raw or args.json:
        # Show raw output
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            print(f"OCR (raw):     {results['ocr']}")
            print(f"Caption (raw): {results['caption']}")
    else:
        # Show parsed output
        ocr_cleaned = parse_florence_ocr(results.get("ocr", ""))
        ocr_meaningful = extract_meaningful_ocr(ocr_cleaned)
        caption = parse_florence_caption(results.get("caption", ""))

        print(f"OCR (cleaned):     {ocr_cleaned}")
        print(f"OCR (meaningful):  {ocr_meaningful}")
        print(f"Caption (parsed):  {caption}")

        if args.verbose:
            print(f"\n--- Raw OCR ---\n{results.get('ocr', '')}")
            print(f"\n--- Raw Caption ---\n{results.get('caption', '')}")

    if args.verbose:
        print(f"\nTime: {elapsed:.2f}s")


if __name__ == "__main__":
    main()