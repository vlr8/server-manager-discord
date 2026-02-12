"""
Content Analyzer Module
Analyzes message content using:
- Bad word matching
- Learned patterns from historical data
- Sentiment analysis
- Toxicity scoring
"""

import re
import json
from typing import Dict, List, Tuple, Optional
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# Try to import VADER for sentiment analysis
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    VADER_AVAILABLE = True
except ImportError:
    VADER_AVAILABLE = False
    print("⚠️  vaderSentiment not installed. Run: pip install vaderSentiment")

import common.moderation_db as mdb


@dataclass
class AnalysisResult:
    """Result of content analysis."""
    is_flagged: bool
    confidence: float
    reasons: List[str]
    matched_words: List[str]
    matched_patterns: List[str]
    sentiment_score: float  # -1 (negative) to 1 (positive)
    toxicity_score: float   # 0 to 1
    should_delete: bool
    should_timeout: bool
    censored_content: str


class ContentAnalyzer:
    """
    Analyzes message content for ToS violations using multiple methods.
    """
    
    # Severity thresholds
    TOXICITY_THRESHOLD = 0.6
    SENTIMENT_THRESHOLD = -0.5
    AUTO_DELETE_THRESHOLD = 0.7
    AUTO_TIMEOUT_THRESHOLD = 0.85
    
    # Characters used for censoring
    CENSOR_CHAR = "█"
    
    def __init__(self):
        # Initialize sentiment analyzer
        self.sentiment_analyzer = None
        if VADER_AVAILABLE:
            self.sentiment_analyzer = SentimentIntensityAnalyzer()
        
        # Load bad words from database
        self.bad_words = {}
        self.load_bad_words()
        
        # Load learned patterns
        self.patterns = []
        self.load_patterns()
        
        # Toxicity indicators (supplementary patterns)
        self.toxicity_patterns = [
            # Aggressive patterns
            (r'\b(kill|die|death)\s+(your)?self\b', 1.0, 'self_harm_encouragement'),
            (r'\bkys\b', 1.0, 'self_harm_encouragement'),
            (r'\bi(\s+will|\'ll)\s+(kill|hurt|find)\s+(you|u)\b', 0.9, 'threat'),
            (r'\b(hope\s+you|you\s+should)\s+(die|get\s+hit)\b', 0.9, 'death_wish'),
            
            # Harassment patterns
            (r'\b(nobody|no\s*one)\s+(likes?|wants?|cares?\s+about)\s+(you|u)\b', 0.7, 'harassment'),
            (r'\byou(\s+are|\'re)\s+(worthless|pathetic|disgusting|trash)\b', 0.7, 'harassment'),
            (r'\b(go\s+)?(kill|hang|shoot)\s+yourself\b', 1.0, 'self_harm_encouragement'),
            
            # Slur patterns (generic - you should customize)
            (r'\b(retard|retarded)\b', 0.6, 'slur'),
            (r'\b(fagg?ot|f[a4]g)\b', 0.8, 'slur'),
            
            # Spam/flood patterns
            (r'(.)\1{10,}', 0.4, 'spam'),  # Repeated characters
            (r'(\b\w+\b)(\s+\1){4,}', 0.5, 'spam'),  # Repeated words
        ]
        
        # Compile toxicity patterns
        self.compiled_toxicity = [
            (re.compile(pattern, re.IGNORECASE), score, category)
            for pattern, score, category in self.toxicity_patterns
        ]
    
    def load_bad_words(self):
        """Load bad words from the moderation database."""
        try:
            words = mdb.get_bad_words()
            self.bad_words = {w['word']: w['severity'] for w in words}
            print(f"Loaded {len(self.bad_words)} bad words")
        except Exception as e:
            print(f"⚠️  Could not load bad words: {e}")
            self.bad_words = {}
    
    def load_patterns(self):
        """Load learned patterns from database."""
        try:
            self.patterns = mdb.get_learned_patterns(min_confidence=0.3)
            print(f"Loaded {len(self.patterns)} learned patterns")
        except Exception as e:
            print(f"⚠️  Could not load patterns: {e}")
            self.patterns = []
    
    def reload(self):
        """Reload bad words and patterns from database."""
        self.load_bad_words()
        self.load_patterns()
    
    def analyze(self, content: str, author_id: str = None) -> AnalysisResult:
        """
        Analyze message content for violations.
        
        Args:
            content: The message text to analyze
            author_id: Optional user ID for repeat offender checking
        
        Returns:
            AnalysisResult with all analysis details
        """
        if not content or not content.strip():
            return AnalysisResult(
                is_flagged=False, confidence=0, reasons=[], matched_words=[],
                matched_patterns=[], sentiment_score=0, toxicity_score=0,
                should_delete=False, should_timeout=False, censored_content=content
            )
        
        content_lower = content.lower()
        reasons = []
        matched_words = []
        matched_patterns = []
        toxicity_score = 0.0
        
        # 1. Check bad words
        word_score, word_matches = self._check_bad_words(content_lower)
        if word_matches:
            matched_words = word_matches
            toxicity_score = max(toxicity_score, word_score)
            reasons.append(f"bad_words:{','.join(word_matches[:3])}")
        
        # 2. Check toxicity patterns
        pattern_score, pattern_matches, pattern_categories = self._check_toxicity_patterns(content)
        if pattern_matches:
            matched_patterns.extend(pattern_matches)
            toxicity_score = max(toxicity_score, pattern_score)
            for cat in set(pattern_categories):
                reasons.append(f"pattern:{cat}")
        
        # 3. Check learned patterns
        learned_score, learned_matches = self._check_learned_patterns(content_lower)
        if learned_matches:
            matched_patterns.extend(learned_matches)
            toxicity_score = max(toxicity_score, learned_score * 0.8)  # Slightly lower weight
            reasons.append("learned_pattern")
        
        # 4. Sentiment analysis
        sentiment_score = self._analyze_sentiment(content)
        if sentiment_score < self.SENTIMENT_THRESHOLD:
            # Very negative sentiment adds to toxicity
            toxicity_score = max(toxicity_score, toxicity_score + abs(sentiment_score) * 0.3)
            reasons.append("negative_sentiment")
        
        # 5. Check for repeat offender
        if author_id:
            offense_count = mdb.get_user_offense_count(author_id, hours=24)
            if offense_count >= 3:
                toxicity_score = min(1.0, toxicity_score + 0.2)
                reasons.append(f"repeat_offender:{offense_count}")
        
        # Determine actions
        is_flagged = toxicity_score >= self.TOXICITY_THRESHOLD or len(matched_words) > 0
        should_delete = toxicity_score >= self.AUTO_DELETE_THRESHOLD or len(matched_words) > 0
        should_timeout = toxicity_score >= self.AUTO_TIMEOUT_THRESHOLD
        
        # Calculate confidence
        confidence = min(1.0, toxicity_score)
        
        # Generate censored content
        censored_content = self._censor_content(content, matched_words, matched_patterns)
        
        return AnalysisResult(
            is_flagged=is_flagged,
            confidence=confidence,
            reasons=reasons,
            matched_words=matched_words,
            matched_patterns=matched_patterns,
            sentiment_score=sentiment_score,
            toxicity_score=toxicity_score,
            should_delete=should_delete,
            should_timeout=should_timeout,
            censored_content=censored_content
        )
    
    def _check_bad_words(self, content_lower: str) -> Tuple[float, List[str]]:
        """Check for bad words and return max severity and matches."""
        matches = []
        max_severity = 0
        
        for word, severity in self.bad_words.items():
            # Use word boundary matching
            pattern = r'\b' + re.escape(word) + r'\b'
            if re.search(pattern, content_lower):
                matches.append(word)
                max_severity = max(max_severity, severity)
                # Update match count in database
                mdb.increment_word_match(word)
        
        # Normalize severity to 0-1 scale (assuming max severity is 5)
        normalized_score = min(1.0, max_severity / 5.0) if max_severity > 0 else 0
        
        return normalized_score, matches
    
    def _check_toxicity_patterns(self, content: str) -> Tuple[float, List[str], List[str]]:
        """Check toxicity patterns and return score, matches, and categories."""
        max_score = 0
        matches = []
        categories = []
        
        for pattern, score, category in self.compiled_toxicity:
            if pattern.search(content):
                max_score = max(max_score, score)
                matches.append(category)
                categories.append(category)
        
        return max_score, matches, categories
    
    def _check_learned_patterns(self, content_lower: str) -> Tuple[float, List[str]]:
        """Check learned patterns."""
        max_score = 0
        matches = []
        
        for pattern_data in self.patterns:
            pattern = pattern_data['pattern']
            confidence = pattern_data['confidence']
            
            try:
                if re.search(pattern, content_lower, re.IGNORECASE):
                    max_score = max(max_score, confidence)
                    matches.append(pattern)
                    mdb.update_pattern_stats(pattern, matched=True)
            except re.error:
                # Invalid regex pattern
                continue
        
        return max_score, matches
    
    def _analyze_sentiment(self, content: str) -> float:
        """
        Analyze sentiment using VADER.
        Returns compound score from -1 (negative) to 1 (positive).
        """
        if not self.sentiment_analyzer:
            return 0.0
        
        try:
            scores = self.sentiment_analyzer.polarity_scores(content)
            return scores['compound']
        except:
            return 0.0
    
    def _censor_content(self, content: str, matched_words: List[str], matched_patterns: List[str]) -> str:
        """
        Censor the matched bad words and patterns in the content.
        """
        censored = content
        
        # Censor bad words
        for word in matched_words:
            # Create a case-insensitive pattern
            pattern = re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE)
            censored = pattern.sub(self.CENSOR_CHAR * len(word), censored)
        
        # For pattern matches, try to identify and censor the matched portion
        for pattern in matched_patterns:
            try:
                match = re.search(pattern, censored, re.IGNORECASE)
                if match:
                    matched_text = match.group(0)
                    censored = censored.replace(matched_text, self.CENSOR_CHAR * len(matched_text))
            except:
                continue
        
        return censored


# ============== PATTERN LEARNING ==============

def learn_patterns_from_samples(min_frequency: int = 3) -> int:
    """
    Analyze training samples to extract common patterns.
    
    Returns number of new patterns learned.
    """
    conn = mdb.get_connection()
    cursor = conn.cursor()
    
    # Get all bad samples
    cursor.execute("SELECT content FROM training_samples WHERE label = 'bad'")
    bad_samples = [row['content'] for row in cursor.fetchall()]
    conn.close()
    
    if not bad_samples:
        print("No training samples found")
        return 0
    
    print(f"Analyzing {len(bad_samples)} training samples...")
    
    # Extract n-grams (2-4 words)
    ngram_counts = Counter()
    
    for content in bad_samples:
        # Clean and tokenize
        words = re.findall(r'\b\w+\b', content.lower())
        
        # Extract n-grams
        for n in range(2, 5):
            for i in range(len(words) - n + 1):
                ngram = ' '.join(words[i:i+n])
                ngram_counts[ngram] += 1
    
    # Filter to frequent n-grams
    frequent_ngrams = [
        (ngram, count) for ngram, count in ngram_counts.items()
        if count >= min_frequency and len(ngram) > 5
    ]
    
    # Add as learned patterns
    added = 0
    for ngram, count in frequent_ngrams:
        # Calculate confidence based on frequency
        confidence = min(0.9, 0.3 + (count / len(bad_samples)) * 0.6)
        
        # Create regex pattern (with word boundaries)
        pattern = r'\b' + re.escape(ngram) + r'\b'
        
        if mdb.add_learned_pattern(pattern, 'ngram', confidence):
            added += 1
    
    print(f"Learned {added} new patterns from samples")
    return added


def import_bad_messages_as_samples(flagged_file: str = "flagged_messages.json"):
    """
    Import previously flagged messages as training samples.
    """
    if not Path(flagged_file).exists():
        print(f"❌ File not found: {flagged_file}")
        return 0
    
    with open(flagged_file, 'r') as f:
        data = json.load(f)
    
    messages = data.get('flagged_messages', [])
    imported = 0
    
    for msg in messages:
        content = msg.get('content', '')
        if content:
            mdb.add_training_sample(content, 'bad', 'flagged_import')
            imported += 1
    
    print(f"Imported {imported} flagged messages as training samples")
    return imported


# ============== UTILITY FUNCTIONS ==============

def quick_check(content: str) -> bool:
    """
    Quick check if content might need full analysis.
    Used for performance optimization.
    """
    analyzer = ContentAnalyzer()
    result = analyzer.analyze(content)
    return result.is_flagged


def analyze_and_print(content: str):
    """Analyze content and print detailed results."""
    analyzer = ContentAnalyzer()
    result = analyzer.analyze(content)
    
    print(f"\n{'='*50}")
    print(f"Content: {content[:100]}...")
    print(f"{'='*50}")
    print(f"Flagged: {result.is_flagged}")
    print(f"Confidence: {result.confidence:.2f}")
    print(f"Toxicity Score: {result.toxicity_score:.2f}")
    print(f"Sentiment Score: {result.sentiment_score:.2f}")
    print(f"Should Delete: {result.should_delete}")
    print(f"Should Timeout: {result.should_timeout}")
    print(f"Reasons: {', '.join(result.reasons)}")
    print(f"Matched Words: {result.matched_words}")
    print(f"Matched Patterns: {result.matched_patterns}")
    print(f"Censored: {result.censored_content}")
    
    return result


# Singleton analyzer instance
_analyzer_instance = None

def get_analyzer() -> ContentAnalyzer:
    """Get the singleton analyzer instance."""
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = ContentAnalyzer()
    return _analyzer_instance


if __name__ == "__main__":
    # Test the analyzer
    mdb.init_moderation_db()
    
    # Add some test bad words
    mdb.add_bad_words_bulk(['badword', 'offensive', 'slur'], severity=3, category='test')
    
    # Test analysis
    test_messages = [
        "Hello, how are you today?",
        "This is a badword message",
        "You are worthless and nobody likes you",
        "kys",
        "I hope you have a great day!",
    ]
    
    analyzer = ContentAnalyzer()
    
    for msg in test_messages:
        result = analyzer.analyze(msg)
        print(f"\n'{msg[:50]}...'")
        print(f"  Flagged: {result.is_flagged}, Toxicity: {result.toxicity_score:.2f}, Delete: {result.should_delete}")
