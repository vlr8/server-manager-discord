# vision/parsing.py
"""
Shared parsing utilities for vision pipeline.

Handles:
- Florence OCR output cleaning (strip <loc_XXX> tags, deduplicate)
- Florence caption summarization (trim verbose descriptions)
- CLIP tag deduplication and normalization
- Image type classification (meme, selfie, screenshot, product, etc.)
- Combined output generation for bot consumption

The combined output is a SHORT string designed to be injected into
Claude's context so Nadiabot can react naturally to images.
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("Vision.Parsing")


# ============== IMAGE TYPE CLASSIFICATION SIGNALS ==============
# These keyword lists drive the classify_image_type() function.
# Meme signals come from CLIP tags or Florence captions that suggest
# meme/comic/reaction image format. Document signals are negative --
# they indicate screenshots/articles that the bot should mostly ignore.

MEME_SIGNALS = [
    "meme", "cartoon", "comic", "funny", "text overlay",
    "impact font", "white text", "bold text",
    "top text", "bottom text", "reaction image",
    "demotivational", "template", "macro",
    "drake format", "distracted boyfriend", "wojak",
    "pepe", "chad", "soyjak", "gigachad",
    "deep fried", "shitpost", "surreal",
]

DOCUMENT_SIGNALS = [
    "screenshot", "chat", "message", "email", "article",
    "news", "document", "webpage", "browser", "terminal",
    "code", "spreadsheet", "table", "form", "receipt",
    "twitter", "tweet", "reddit", "discord",
    "text message", "notification", "ui", "interface",
]

SELFIE_SIGNALS = [
    "selfie", "self portrait", "mirror", "bathroom",
    "close up of face", "close-up", "looking at camera",
    "phone camera", "front facing",
]

PRODUCT_SIGNALS = [
    "product", "packaging", "box", "store", "official",
    "vinyl figure", "funko", "action figure", "toy",
    "merchandise", "brand", "logo", "advertisement",
]

FOOD_SIGNALS = [
    "food", "meal", "dish", "plate", "restaurant",
    "cooking", "kitchen", "sushi", "pizza", "burger",
    "dessert", "cake", "coffee", "drink", "cocktail",
]

FASHION_SIGNALS = [
    "outfit", "dress", "wearing", "fashion", "style",
    "heels", "shoes", "boots", "jacket", "skirt",
    "jewelry", "accessory", "handbag", "sunglasses",
]

TRAVEL_SIGNALS = [
    "beach", "mountain", "city", "skyline", "landmark",
    "tourist", "vacation", "hotel", "pool", "sunset",
    "architecture", "building", "monument", "temple",
]

ANIME_CARTOON_SIGNALS = [
    "anime", "manga", "cartoon", "animated", "illustration",
    "drawing", "sketch", "cel shaded", "2d",
    "visual novel", "anime screenshot", "chibi", "webtoon",
]

MEDICAL_SIGNALS = [
    "pill", "pills", "tablet", "capsule", "medication",
    "medicine", "prescription", "pharmacy", "syringe",
    "needle", "injection", "vial", "bottle", "hormone",
    "estrogen", "testosterone", "spironolactone", "progesterone",
    "hrt", "supplement", "bandage", "surgery", "surgical",
    "hospital", "clinic", "doctor", "medical", "treatment",
    "drug", "blister pack", "patch", "gel",
]


@dataclass
class ImageAnalysis:
    """
    Combined analysis result from CLIP + Florence pipeline.

    This is the structured output that gets converted to a bot-friendly
    description string via to_bot_description().
    """
    # Classification
    image_type: str = "unknown"  # meme, selfie, screenshot, product, food, fashion, travel, photo
    confidence: float = 0.0     # 0-1 how confident the classification is

    # From CLIP: visual style and content tags
    clip_scene: str = ""            # First CLIP tag (main scene description)
    clip_tags: list = field(default_factory=list)  # Deduplicated, normalized tags
    clip_raw: str = ""              # Original CLIP output for debugging

    # From Florence: text content and scene understanding
    ocr_text: str = ""              # Cleaned OCR text (no location tags)
    ocr_words: list = field(default_factory=list)  # Individual words extracted
    florence_caption: str = ""      # Summarized caption (first 1-2 sentences)
    florence_raw_caption: str = ""  # Full caption for debugging

    # Derived
    has_text: bool = False          # Whether meaningful text was found in image
    text_word_count: int = 0        # How many words of text in the image
    is_meme: bool = False           # Shortcut for image_type == "meme"

    def to_bot_description(self) -> str:
        """
        Generate a concise description string for injection into bot context.

        Format varies by image type:
        - [MEME] <caption> | Text: "<ocr_text>"
        - [SELFIE] <caption> | <clip details>
        - [SCREENSHOT] <caption> -- bot usually ignores these
        - [PHOTO] <caption> | <clip details>

        Kept SHORT (under ~200 chars ideally) so it doesn't bloat the prompt.
        """
        type_tag = f"[{self.image_type.upper()}]"

        # Pick the best primary description:
        # Florence caption is more descriptive, CLIP scene is a fallback
        primary = self.florence_caption or self.clip_scene or "image"

        # Trim primary to ~150 chars max
        if len(primary) > 150:
            # Cut at last sentence boundary before 150 chars
            cut = primary[:150].rfind('. ')
            if cut > 50:
                primary = primary[:cut + 1]
            else:
                primary = primary[:147] + "..."

        parts = [type_tag, primary]

        # Add OCR text when present (meme jokes, labels, captions, etc.)
        if self.has_text:
            ocr_display = self.ocr_text[:100]
            if len(self.ocr_text) > 100:
                ocr_display += "..."
            parts.append(f'Text in image: "{ocr_display}"')

        # Add relevant CLIP tags that aren't redundant with caption
        # (e.g. demographics, emotions, specific objects)
        extra_tags = self._get_non_redundant_tags(primary)
        if extra_tags:
            parts.append(", ".join(extra_tags[:4]))

        return " | ".join(parts)

    def _get_non_redundant_tags(self, caption: str) -> list[str]:
        """
        Return CLIP tags that add info not already in the caption.
        Filters out generic/redundant tags to keep description tight.
        """
        if not self.clip_tags:
            return []

        caption_lower = caption.lower()
        # Tags to always skip (too generic or just describe the medium)
        skip_patterns = {
            "image", "photo", "picture", "illustration", "digital",
            "high quality", "detailed", "realistic", "professional",
            "stock photo", "close up", "full body", "portrait",
            "hd", "4k", "8k", "trending", "artstation",
        }

        useful = []
        for tag in self.clip_tags[1:]:  # Skip first tag (scene, already used)
            tag_lower = tag.lower().strip()
            # Skip if too short, generic, or already in caption
            if len(tag_lower) < 3:
                continue
            if tag_lower in skip_patterns:
                continue
            if any(skip in tag_lower for skip in skip_patterns):
                continue
            if tag_lower in caption_lower:
                continue
            useful.append(tag)

        return useful


# ============== FLORENCE OCR PARSING ==============

# Regex to strip Florence's <loc_XXX> bounding box tags and XML artifacts
_LOC_TAG_RE = re.compile(r'<loc_\d+>')
_XML_TAG_RE = re.compile(r'</?\w+/?>')  # <s>, </s>, etc.


def parse_florence_ocr(raw_ocr: str) -> str:
    """
    Clean Florence-2 OCR output by stripping location tags and XML artifacts.

    Input:  "</s><s><s><s>POP!<loc_230><loc_147>TRANNERLAND<loc_470>..."
    Output: "POP! TRANNERLAND 01 BOBOLF-T LERA VINYL FIGURE..."

    Returns cleaned text with words separated by spaces, deduplicated.
    """
    if not raw_ocr:
        return ""

    # Strip XML tags (<s>, </s>, etc.)
    cleaned = _XML_TAG_RE.sub(' ', raw_ocr)

    # Strip <loc_XXX> bounding box tags
    cleaned = _LOC_TAG_RE.sub(' ', cleaned)

    # Collapse whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    # Deduplicate consecutive repeated words/phrases
    # Florence sometimes repeats words that appear multiple times on the image
    cleaned = _deduplicate_consecutive(cleaned)

    return cleaned


def _deduplicate_consecutive(text: str) -> str:
    """
    Remove consecutive duplicate words/short phrases in OCR output.

    "CHOKING HAZARD CHOKING HAZARD WARNING" -> "CHOKING HAZARD WARNING"
    """
    words = text.split()
    if len(words) <= 1:
        return text

    result = [words[0]]
    i = 1
    while i < len(words):
        # Check for 1-3 word consecutive repeats
        is_repeat = False
        for window in range(1, min(4, i + 1)):
            if i + window <= len(words):
                prev_chunk = words[i - window:i]
                curr_chunk = words[i:i + window]
                if prev_chunk == curr_chunk:
                    i += window
                    is_repeat = True
                    break
        if not is_repeat:
            result.append(words[i])
            i += 1

    return ' '.join(result)


def extract_meaningful_ocr(cleaned_ocr: str, max_words: int = 40) -> str:
    """
    Extract the meaningful portion of OCR text, filtering out boilerplate.

    Strips common packaging/legal text like warnings, copyright notices,
    barcodes, etc. that don't contribute to understanding the image content.

    Args:
        cleaned_ocr: Already-cleaned OCR text (from parse_florence_ocr)
        max_words: Maximum words to return

    Returns:
        The meaningful portion of OCR text, or "" if nothing useful.
    """
    if not cleaned_ocr:
        return ""

    # Boilerplate patterns to strip (packaging, legal, warnings)
    boilerplate_patterns = [
        r'WARNING:?\s*CHOKING\s*HAZARD.*',
        r'ADVERTENCIA.*',
        r'AVERTISSEMENT.*',
        r'Small\s*parts\.?.*',
        r'Not\s*for\s*children\s*under.*',
        r'MADE\s*IN\s*(CHINA|VIETNAM|TAIWAN).*',
        r'[©®™]\s*\d{4}.*',
        r'All\s*rights\s*reserved.*',
        r'www\.\S+',
        r'http\S+',
    ]

    text = cleaned_ocr
    for pattern in boilerplate_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)

    # Collapse whitespace after removals
    text = re.sub(r'\s+', ' ', text).strip()

    # Filter out pure punctuation/symbol tokens (no alphanumeric content).
    # Prevents OCR noise like "-", ".", "—" from counting as text and
    # incorrectly triggering meme classification or suppressing selfie detection.
    words = text.split()
    words = [w for w in words if any(c.isalnum() for c in w)]

    if len(words) > max_words:
        words = words[:max_words]

    return ' '.join(words)


# ============== FLORENCE CAPTION PARSING ==============

def parse_florence_caption(raw_caption: str, max_sentences: int = 2) -> str:
    """
    Trim Florence-2's verbose caption to the first N useful sentences.

    Florence captions tend to over-describe: multiple paragraphs about
    spatial layout, background details, etc. We want the core description.

    Input:  "</s><s>The image is of a Funko Pop!... (3 paragraphs)"
    Output: "Funko Pop vinyl figure of character Lera from Trannerland in original packaging."
    """
    if not raw_caption:
        return ""

    # Strip XML tags
    cleaned = _XML_TAG_RE.sub(' ', raw_caption)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    # Remove filler openings that Florence loves to generate
    filler_starts = [
        r'^The image (is of|shows|depicts|features|contains|presents)\s+',
        r'^This is (an? |the )?(image|photo|picture|illustration) (of|showing|depicting)\s+',
        r'^In this (image|photo|picture),?\s+',
    ]
    for pattern in filler_starts:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

    # Re-capitalize first letter after stripping
    if cleaned and cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]

    # Split into sentences and take first N
    # Handle both '. ' and '.\n' as sentence boundaries
    sentences = re.split(r'(?<=[.!?])\s+', cleaned)
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        return cleaned[:200]

    result = ' '.join(sentences[:max_sentences])

    # Final length cap
    if len(result) > 250:
        cut = result[:250].rfind('. ')
        if cut > 80:
            result = result[:cut + 1]
        else:
            result = result[:247] + "..."

    return result


# ============== CLIP OUTPUT PARSING ==============

def parse_clip_tags(raw_description: str) -> tuple[str, list[str]]:
    """
    Parse CLIP Interrogator comma-separated output into scene + tag list.

    First tag is the scene description, rest are style/content tags.
    Deduplicates and normalizes tags.

    Input:  "a close up of a pop vinyl figure of a woman with a gun, as a funko pop!, ..."
    Output: ("a close up of a pop vinyl figure of a woman with a gun",
             ["funko pop", "vinyl action figure", "pop realism", ...])
    """
    if not raw_description:
        return "", []

    tags = [t.strip() for t in raw_description.split(",") if t.strip()]
    if not tags:
        return "", []

    scene = tags[0]
    rest = tags[1:]

    # Normalize: strip common prefixes CLIP adds
    normalized = []
    seen_lower = {scene.lower()}  # Avoid duplicating the scene description
    strip_prefixes = ["as a ", "as an ", "in the style of ", "like a "]

    for tag in rest:
        tag_clean = tag.strip()
        for prefix in strip_prefixes:
            if tag_clean.lower().startswith(prefix):
                tag_clean = tag_clean[len(prefix):]
                break
        tag_lower = tag_clean.lower()
        if tag_lower not in seen_lower and len(tag_clean) > 2:
            normalized.append(tag_clean)
            seen_lower.add(tag_lower)

    return scene, normalized


# ============== IMAGE TYPE CLASSIFICATION ==============

def classify_image_type(
    clip_tags: list[str],
    ocr_text: str,
    florence_caption: str,
    image_path: Optional[str] = None,
) -> tuple[str, float]:
    """
    Classify image into a type based on combined CLIP + Florence signals.

    Checks against signal keyword lists in priority order:
    1. Document/screenshot (negative - bot mostly ignores)
    2. Meme (text overlay on image, reaction format, etc.)
    3. Selfie
    4. Product/merch
    5. Food
    6. Fashion
    7. Travel/scenery
    8. Generic photo (fallback)

    Also uses heuristics:
    - Moderate text (3-40 words) on a non-document image -> likely meme
    - Very tall/narrow aspect ratio -> likely screenshot
    - Face close-up -> likely selfie

    Args:
        clip_tags: Normalized CLIP tags list
        ocr_text: Cleaned OCR text from Florence
        florence_caption: Parsed Florence caption
        image_path: Optional path for aspect ratio heuristic

    Returns:
        (image_type, confidence) where confidence is 0.0-1.0
    """
    # Combine all text sources for keyword matching
    all_text = ' '.join(clip_tags).lower()
    caption_lower = florence_caption.lower() if florence_caption else ""
    combined = f"{all_text} {caption_lower}"

    # Count matches against each signal list
    def count_matches(signals: list[str], text: str) -> int:
        return sum(1 for sig in signals if sig in text)

    doc_score = count_matches(DOCUMENT_SIGNALS, combined)
    meme_score = count_matches(MEME_SIGNALS, combined)
    selfie_score = count_matches(SELFIE_SIGNALS, combined)
    product_score = count_matches(PRODUCT_SIGNALS, combined)
    food_score = count_matches(FOOD_SIGNALS, combined)
    fashion_score = count_matches(FASHION_SIGNALS, combined)
    travel_score = count_matches(TRAVEL_SIGNALS, combined)
    anime_score = count_matches(ANIME_CARTOON_SIGNALS, combined)
    medical_score = count_matches(MEDICAL_SIGNALS, combined)

    # --- Aspect ratio heuristic (screenshots are usually tall/narrow) ---
    if image_path:
        try:
            from PIL import Image
            img = Image.open(image_path)
            w, h = img.size
            aspect = h / w if w > 0 else 1.0
            # Very tall images (aspect > 2.5) are almost always screenshots
            if aspect > 2.5:
                doc_score += 3
            # Very wide images (aspect < 0.4) are usually banners/memes
            elif aspect < 0.4:
                meme_score += 1
        except Exception:
            pass

    # --- Text heuristic: any text overlay on non-document = likely meme ---
    ocr_word_count = len(ocr_text.split()) if ocr_text else 0
    ocr_line_count = ocr_text.count('\n') + 1 if ocr_text else 0

    if ocr_word_count >= 1 and ocr_word_count <= 40 and ocr_line_count <= 6:
        if doc_score == 0 and medical_score == 0:
            meme_score += 1

    # --- Anime/cartoon heuristic ---
    # Anime with text overlay is almost always a reaction meme
    if anime_score >= 1 and ocr_word_count >= 1:
        meme_score += 2
    # Anime/cartoon faces aren't selfies - suppress false positives
    if anime_score >= 1:
        selfie_score = max(0, selfie_score - 2)

    # Any text overlay suppresses selfie - real selfies don't have text on them
    if ocr_word_count >= 1:
        selfie_score = max(0, selfie_score - 2)

    # --- Priority-ordered classification ---
    # Document/screenshot: high priority negative signal
    if doc_score >= 2:
        return "screenshot", min(1.0, doc_score * 0.3)

    # Meme: text overlay + visual signals
    if meme_score >= 2 or (meme_score >= 1 and ocr_word_count >= 1):
        return "meme", min(1.0, meme_score * 0.3)

    # Text-heavy non-document, non-meme: moderate text with no strong signals
    # Treat as meme if there's meaningful text overlay
    if ocr_word_count >= 5 and doc_score == 0:
        return "meme", 0.4

    # Selfie
    if selfie_score >= 1:
        return "selfie", min(1.0, selfie_score * 0.4)

    # Product/merch
    if product_score >= 2:
        return "product", min(1.0, product_score * 0.3)

    # Medical/HRT
    if medical_score >= 1:
        return "medical", min(1.0, medical_score * 0.4)

    # Food
    if food_score >= 1:
        return "food", min(1.0, food_score * 0.4)

    # Fashion
    if fashion_score >= 1:
        return "fashion", min(1.0, fashion_score * 0.4)

    # Travel
    if travel_score >= 1:
        return "travel", min(1.0, travel_score * 0.4)

    # Fallback: generic photo
    return "photo", 0.2


# ============== COMBINED OUTPUT ==============

def combine_analysis(
    clip_raw: str = "",
    florence_ocr_raw: str = "",
    florence_caption_raw: str = "",
    image_path: Optional[str] = None,
) -> ImageAnalysis:
    """
    Combine raw outputs from CLIP and Florence into a single ImageAnalysis.

    This is the main entry point called by the vision pipeline after both
    models have run. It parses, classifies, and produces a bot-ready result.

    Args:
        clip_raw: Raw CLIP Interrogator output (comma-separated tags)
        florence_ocr_raw: Raw Florence OCR output (with <loc_XXX> tags)
        florence_caption_raw: Raw Florence caption output (verbose)
        image_path: Optional path for aspect ratio heuristic

    Returns:
        ImageAnalysis with all fields populated and to_bot_description() ready.
    """
    # Parse individual outputs
    clip_scene, clip_tags = parse_clip_tags(clip_raw)
    ocr_cleaned = parse_florence_ocr(florence_ocr_raw)
    ocr_meaningful = extract_meaningful_ocr(ocr_cleaned)
    caption = parse_florence_caption(florence_caption_raw)

    # Classify image type
    image_type, confidence = classify_image_type(
        clip_tags, ocr_meaningful, caption, image_path
    )

    ocr_word_count = len(ocr_meaningful.split()) if ocr_meaningful else 0
    has_text = ocr_word_count >= 1  # Any detected text is meaningful

    analysis = ImageAnalysis(
        image_type=image_type,
        confidence=confidence,
        clip_scene=clip_scene,
        clip_tags=clip_tags,
        clip_raw=clip_raw,
        ocr_text=ocr_meaningful,
        ocr_words=ocr_meaningful.split() if ocr_meaningful else [],
        florence_caption=caption,
        florence_raw_caption=florence_caption_raw,
        has_text=has_text,
        text_word_count=ocr_word_count,
        is_meme=(image_type == "meme"),
    )

    logger.info(
        f"Combined analysis: type={image_type} (conf={confidence:.2f}) | "
        f"has_text={has_text} ({ocr_word_count} words) | "
        f"clip_tags={len(clip_tags)} | caption={len(caption)} chars"
    )

    return analysis