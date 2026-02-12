# vision/interrogator.py
"""
Image analysis pipeline for Nadiabot.

Orchestrates two models:
1. CLIP Interrogator - fast visual style/content tagging (~2s)
2. Florence-2 - OCR text extraction + detailed captioning (~3s)

Both run concurrently via asyncio.to_thread(), then results are combined
through vision.parsing into a concise bot-friendly description.

The combined description is what gets stored in BufferedMessage.image_description
and injected into Claude's context for response generation.

Usage:
    from vision.interrogator import describe_image_from_url

    # Returns bot-ready string like:
    # "[MEME] Funko Pop figure of Lera from Trannerland | Text: 'POP! TRANNERLAND LERA'"
    description = await describe_image_from_url(url, timeout_seconds=20.0)

    # For local files:
    from vision.interrogator import describe_image_combined
    description = await describe_image_combined("/path/to/image.png")
"""

from PIL import Image
import asyncio
import logging
import tempfile
import os
from typing import Optional

logger = logging.getLogger("Vision")


# ============== CLIP INTERROGATOR (Layer 1: Visual Style) ==============

class ImageInterrogator:
    """
    CLIP Interrogator wrapper for image understanding.
    Singleton pattern - loads model once, reuses for all images.

    Provides fast visual tagging: scene description, style, demographics,
    emotions, objects. Good at "what kind of image is this" but cannot
    read text in images.
    """
    _instance = None
    _interrogator = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _ensure_loaded(self):
        """Lazy load the model on first use."""
        if self._interrogator is None:
            logger.info("Loading CLIP Interrogator model (first use)...")
            from clip_interrogator import Config, Interrogator
            config = Config(
                clip_model_name="ViT-L-14/openai",
                quiet=True,  # Suppress progress bars
            )
            self._interrogator = Interrogator(config)
            # Force ALL model components to float32.
            # clip_interrogator loads clip_model, caption_model (BLIP), and phrase
            # embedding tables (LabelTable.embeds) — some may be float16. When
            # inference runs via asyncio.to_thread(), autocast is thread-local and
            # not carried over, so any float16 weight paired with a float32 activation
            # causes "got Float and Half" errors. Converting every nn.Module and
            # LabelTable.embeds ensures consistency regardless of thread context.
            import torch
            for attr in vars(self._interrogator).values():
                if isinstance(attr, torch.nn.Module):
                    attr.float()
                elif hasattr(attr, 'embeds'):
                    try:
                        e = attr.embeds
                        if isinstance(e, list):
                            attr.embeds = [
                                t.float() if isinstance(t, torch.Tensor) else t
                                for t in e
                            ]
                        elif isinstance(e, torch.Tensor):
                            attr.embeds = e.float()
                    except Exception:
                        pass
            logger.info("CLIP Interrogator loaded successfully")

    def interrogate_sync(self, image_path: str) -> str:
        """
        Synchronous interrogation - call via asyncio.to_thread().
        Returns comma-separated description tags.
        """
        self._ensure_loaded()
        image = Image.open(image_path).convert("RGB")
        # Fast mode is sufficient for Discord bot use - ~2s vs ~8s for full
        description = self._interrogator.interrogate_fast(image)
        return description

    async def interrogate(self, image_path: str) -> str:
        """Async wrapper - runs in thread pool to not block event loop."""
        return await asyncio.to_thread(self.interrogate_sync, image_path)


# ============== MODULE-LEVEL SINGLETONS ==============

_interrogator: Optional[ImageInterrogator] = None


def get_interrogator() -> ImageInterrogator:
    """Get or create the singleton CLIP interrogator."""
    global _interrogator
    if _interrogator is None:
        _interrogator = ImageInterrogator()
    return _interrogator


# ============== COMBINED PIPELINE ==============

async def describe_image_combined(image_path: str) -> str:
    """
    Run the full CLIP + Florence pipeline on a local image file.

    Both models run concurrently, then results are combined through
    vision.parsing into a single bot-ready description string.

    This is the core analysis function. describe_image_from_url() wraps
    this with download/cleanup logic.

    Args:
        image_path: Path to local image file

    Returns:
        Bot-ready description string, e.g.:
        "[MEME] Funko Pop figure of Lera | Text: 'POP! TRANNERLAND LERA'"
        or "" on failure.
    """
    from vision.parsing import combine_analysis

    # Run CLIP and Florence concurrently for speed
    # Both use asyncio.to_thread internally so they don't block each other
    clip_task = asyncio.create_task(_run_clip(image_path))
    florence_task = asyncio.create_task(_run_florence(image_path))

    # Wait for both, handle individual failures gracefully
    clip_raw = ""
    florence_results = {"ocr": "", "caption": ""}

    try:
        clip_raw = await clip_task
    except Exception as e:
        logger.warning(f"CLIP analysis failed (continuing with Florence only): {e}")

    try:
        florence_results = await florence_task
    except Exception as e:
        logger.warning(f"Florence analysis failed (continuing with CLIP only): {e}")

    # If both failed, return empty
    if not clip_raw and not florence_results.get("ocr") and not florence_results.get("caption"):
        logger.warning("Both CLIP and Florence failed - no image description available")
        return ""

    # Combine through parsing module
    analysis = combine_analysis(
        clip_raw=clip_raw,
        florence_ocr_raw=florence_results.get("ocr", ""),
        florence_caption_raw=florence_results.get("caption", ""),
        image_path=image_path,
    )

    bot_description = analysis.to_bot_description()
    logger.info(f"Combined description ({len(bot_description)} chars): {bot_description[:120]}...")
    return bot_description


async def _run_clip(image_path: str) -> str:
    """Run CLIP Interrogator and return raw tags string."""
    return await get_interrogator().interrogate(image_path)


async def _run_florence(image_path: str) -> dict:
    """
    Run Florence-2 and return raw results dict.
    Handles ImportError gracefully if Florence isn't available.
    """
    try:
        from vision.florence import analyze_image
        return await analyze_image(image_path)
    except ImportError:
        logger.warning("Florence-2 not available (missing transformers/torch?)")
        return {"ocr": "", "caption": ""}
    except Exception as e:
        logger.warning(f"Florence-2 analysis failed: {e}")
        return {"ocr": "", "caption": ""}


# ============== CLIP-ONLY FALLBACK ==============

async def describe_image(image_path: str) -> str:
    """
    CLIP-only description (legacy/fallback).
    Use describe_image_combined() for the full pipeline.
    """
    return await get_interrogator().interrogate(image_path)


# ============== URL DOWNLOAD + ANALYSIS ==============

async def describe_image_from_url(url: str, timeout_seconds: float = 20.0) -> str:
    """
    Download image from URL, run combined CLIP + Florence analysis, clean up.

    This is the main entry point called by persona_bot.py's image scanning.
    Downloads to a temp file, runs the combined pipeline, then deletes the file.

    Args:
        url: Image URL (Discord CDN attachment URL)
        timeout_seconds: Total timeout for download + analysis

    Returns:
        Bot-ready description string or "" on failure.
    """
    import aiohttp

    tmp_path = None
    try:
        # Download image to temp file
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=timeout_seconds / 2)
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"Image download failed: HTTP {resp.status}")
                    return ""
                data = await resp.read()
                if len(data) > 20 * 1024 * 1024:  # 20MB limit
                    logger.warning(f"Image too large: {len(data)} bytes")
                    return ""

        # Write to temp file (both models need a file path)
        suffix = os.path.splitext(url.split("?")[0])[1] or ".jpg"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        # Run combined pipeline with remaining timeout budget
        description = await asyncio.wait_for(
            describe_image_combined(tmp_path),
            timeout=timeout_seconds / 2
        )
        return description

    except asyncio.TimeoutError:
        logger.warning("Image download/analysis timed out")
        return ""
    except Exception as e:
        logger.warning(f"Image processing failed: {e}")
        return ""
    finally:
        # Always clean up temp file
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ============== LEGACY PARSING (kept for backward compatibility) ==============

def parse_interrogator_output(description: str) -> dict:
    """
    Extract structured info from CLIP Interrogator output.
    Legacy function - prefer vision.parsing.combine_analysis() for new code.

    Input: "woman sitting in car, black female, mid 20s, tired expression, ..."
    Output: {
        "scene": "woman sitting in car",
        "demographics": {"gender": "female", ...},
        "emotions": ["tired"],
        "raw_tags": [...]
    }
    """
    tags = [t.strip() for t in description.split(",")]

    result = {
        "raw_tags": tags,
        "scene": tags[0] if tags else "",
        "demographics": {},
        "emotions": [],
        "objects": [],
    }

    gender_keywords = {"female", "male", "woman", "man", "girl", "boy"}
    emotion_keywords = {"tired", "happy", "sad", "angry", "anxious", "smiling", "longing"}

    for tag in tags:
        tag_lower = tag.lower()

        if "female" in tag_lower or "woman" in tag_lower:
            result["demographics"]["gender"] = "female"
        elif "male" in tag_lower or "man" in tag_lower:
            result["demographics"]["gender"] = "male"

        if "20s" in tag_lower or "20's" in tag_lower:
            result["demographics"]["age_range"] = "20s"
        elif "30s" in tag_lower:
            result["demographics"]["age_range"] = "30s"

        for emotion in emotion_keywords:
            if emotion in tag_lower:
                result["emotions"].append(emotion)

    return result


# ============== STANDALONE CLI ==============

def main():
    """CLI entry point for testing image analysis pipeline."""
    import argparse
    import sys
    import time
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Test image analysis pipeline (CLIP + Florence)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m vision.interrogator image.jpg              # Combined CLIP+Florence
  python -m vision.interrogator image.jpg --clip-only   # CLIP only (faster)
  python -m vision.interrogator image.jpg -v --raw      # Show raw model outputs
        """
    )
    parser.add_argument("path", help="Image file to process")
    parser.add_argument("--clip-only", action="store_true",
                        help="Skip Florence, use CLIP only")
    parser.add_argument("--raw", action="store_true",
                        help="Show raw model outputs before parsing")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show timing and debug info")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    path = Path(args.path)
    if not path.exists():
        print(f"Error: Path does not exist: {path}", file=sys.stderr)
        sys.exit(1)

    start = time.time()

    if args.clip_only:
        # CLIP only mode
        interrogator = get_interrogator()
        raw = interrogator.interrogate_sync(str(path))
        elapsed = time.time() - start

        print(f"\nCLIP tags: {raw}")

        if args.verbose:
            from vision.parsing import parse_clip_tags
            scene, tags = parse_clip_tags(raw)
            print(f"\nScene: {scene}")
            print(f"Tags ({len(tags)}): {', '.join(tags[:10])}")
    else:
        # Combined pipeline (need async)
        async def run():
            return await describe_image_combined(str(path))

        bot_desc = asyncio.run(run())
        elapsed = time.time() - start

        print(f"\nBot description: {bot_desc}")

        if args.raw:
            # Also show raw outputs
            print(f"\n--- Running raw outputs ---")
            interrogator = get_interrogator()
            clip_raw = interrogator.interrogate_sync(str(path))
            print(f"CLIP raw: {clip_raw}")

            try:
                from vision.florence import get_florence
                florence_raw = get_florence().analyze_sync(str(path))
                print(f"Florence OCR raw: {florence_raw.get('ocr', '')}")
                print(f"Florence caption raw: {florence_raw.get('caption', '')}")
            except Exception as e:
                print(f"Florence unavailable: {e}")

    if args.verbose:
        print(f"\nTotal time: {elapsed:.2f}s")


if __name__ == "__main__":
    main()