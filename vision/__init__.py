# vision/__init__.py
"""
Vision pipeline for Nadiabot image understanding.

Two-layer architecture:
  Layer 1: CLIP Interrogator - visual style/content tagging (fast, ~2s)
  Layer 2: Florence-2 - OCR text extraction + scene captioning (~3s)

Results are combined through parsing.py into concise bot-friendly descriptions.

Main entry points:
  describe_image_from_url()  - download + full pipeline (used by persona_bot)
  describe_image_combined()  - local file + full pipeline
  get_interrogator()         - direct CLIP access
  get_florence()             - direct Florence access
"""
from .interrogator import describe_image, describe_image_from_url, parse_interrogator_output
from .florence import get_florence
