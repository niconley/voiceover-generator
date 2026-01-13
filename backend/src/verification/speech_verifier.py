"""
Speech verification module using Whisper for transcription and comparison.
"""
from dataclasses import dataclass
from typing import Union, Optional
from pathlib import Path
from io import BytesIO
import logging
import tempfile
import ssl
import urllib.request

# Fix SSL certificate issues on macOS for Whisper model downloads
# Set unverified SSL context to allow model downloads
ssl._create_default_https_context = ssl._create_unverified_context

import whisper
import Levenshtein

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """Result of speech verification."""

    original_text: str
    transcribed_text: str
    accuracy: float
    passed: bool
    word_error_rate: float
    details: str = ""

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return (
            f"Verification: {status} (accuracy={self.accuracy:.1f}%, "
            f"WER={self.word_error_rate:.1f}%)"
        )


class SpeechVerifier:
    """
    Verifies generated speech matches original text using Whisper STT.
    """

    def __init__(
        self,
        model_name: str = "base",
        min_accuracy: float = 95.0
    ):
        """
        Initialize speech verifier.

        Args:
            model_name: Whisper model to use (tiny, base, small, medium, large)
            min_accuracy: Minimum required accuracy percentage

        Models comparison:
        - tiny: Fastest, least accurate (~32x realtime)
        - base: Good balance (~16x realtime) - RECOMMENDED
        - small: Better accuracy (~6x realtime)
        - medium: High accuracy (~2x realtime)
        - large: Best accuracy (~1x realtime)
        """
        self.model_name = model_name
        self.min_accuracy = min_accuracy
        self.model = None

        logger.info(
            f"SpeechVerifier initialized with model '{model_name}', "
            f"min_accuracy={min_accuracy}%"
        )

    def _load_model(self):
        """Lazy load Whisper model on first use."""
        if self.model is None:
            logger.info(f"Loading Whisper model '{self.model_name}'...")
            self.model = whisper.load_model(self.model_name)
            logger.info(f"Whisper model '{self.model_name}' loaded successfully")

    def transcribe(
        self,
        audio_data: Union[bytes, str, Path],
        language: Optional[str] = None
    ) -> str:
        """
        Transcribe audio to text using Whisper.

        Args:
            audio_data: Audio data as bytes or file path
            language: Language code (e.g., 'en', 'es'). If None, auto-detect

        Returns:
            Transcribed text

        Raises:
            Exception: If transcription fails
        """
        self._load_model()

        try:
            # Whisper requires a file path, so save bytes to temp file if needed
            if isinstance(audio_data, bytes):
                with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
                    tmp.write(audio_data)
                    tmp_path = tmp.name

                logger.debug(f"Saved audio to temporary file: {tmp_path}")

                try:
                    result = self.model.transcribe(
                        tmp_path,
                        language=language,
                        fp16=False  # Use FP32 for better compatibility
                    )
                finally:
                    # Clean up temp file
                    Path(tmp_path).unlink(missing_ok=True)
            else:
                # Use file path directly
                result = self.model.transcribe(
                    str(audio_data),
                    language=language,
                    fp16=False
                )

            transcribed_text = result["text"].strip()

            logger.info(
                f"Transcribed audio: '{transcribed_text[:50]}...'"
                if len(transcribed_text) > 50
                else f"Transcribed audio: '{transcribed_text}'"
            )

            return transcribed_text

        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise

    def verify_content(
        self,
        original_text: str,
        audio_data: Union[bytes, str, Path],
        language: Optional[str] = None
    ) -> VerificationResult:
        """
        Verify that audio content matches original text.

        Args:
            original_text: Original text that should be in audio
            audio_data: Audio data to verify
            language: Language code for transcription

        Returns:
            VerificationResult with accuracy and details
        """
        logger.info("Starting speech verification")

        try:
            # Transcribe audio
            transcribed_text = self.transcribe(audio_data, language)

            # Calculate accuracy
            accuracy = self.calculate_accuracy(original_text, transcribed_text)
            wer = self.calculate_word_error_rate(original_text, transcribed_text)

            passed = accuracy >= self.min_accuracy

            details = ""
            if not passed:
                details = (
                    f"Accuracy {accuracy:.1f}% below threshold {self.min_accuracy}%. "
                    f"Original: '{original_text[:50]}...' "
                    f"Transcribed: '{transcribed_text[:50]}...'"
                )

            result = VerificationResult(
                original_text=original_text,
                transcribed_text=transcribed_text,
                accuracy=accuracy,
                passed=passed,
                word_error_rate=wer,
                details=details
            )

            logger.info(f"Verification complete: {result}")
            return result

        except Exception as e:
            logger.error(f"Verification failed: {e}")
            return VerificationResult(
                original_text=original_text,
                transcribed_text="",
                accuracy=0.0,
                passed=False,
                word_error_rate=100.0,
                details=f"Verification error: {e}"
            )

    def calculate_accuracy(
        self,
        original: str,
        transcribed: str
    ) -> float:
        """
        Calculate word-level accuracy between original and transcribed text.

        Uses Levenshtein distance for fuzzy matching.

        Args:
            original: Original text
            transcribed: Transcribed text

        Returns:
            Accuracy percentage (0-100)
        """
        # Normalize texts
        original_normalized = self._normalize_text(original)
        transcribed_normalized = self._normalize_text(transcribed)

        # Calculate Levenshtein similarity
        distance = Levenshtein.distance(original_normalized, transcribed_normalized)
        max_len = max(len(original_normalized), len(transcribed_normalized))

        if max_len == 0:
            return 100.0

        similarity = (1 - distance / max_len) * 100

        logger.debug(
            f"Accuracy calculation: distance={distance}, "
            f"max_len={max_len}, accuracy={similarity:.1f}%"
        )

        return similarity

    def calculate_word_error_rate(
        self,
        original: str,
        transcribed: str
    ) -> float:
        """
        Calculate Word Error Rate (WER) between texts.

        WER = (Substitutions + Deletions + Insertions) / Total Words

        Args:
            original: Original text
            transcribed: Transcribed text

        Returns:
            WER as percentage
        """
        original_words = self._normalize_text(original).split()
        transcribed_words = self._normalize_text(transcribed).split()

        # Use Levenshtein distance on word sequences
        distance = Levenshtein.distance(
            ' '.join(original_words),
            ' '.join(transcribed_words)
        )

        if len(original_words) == 0:
            return 0.0 if len(transcribed_words) == 0 else 100.0

        wer = (distance / len(original_words)) * 100

        logger.debug(f"WER calculation: {wer:.1f}%")
        return wer

    def _normalize_text(self, text: str) -> str:
        """
        Normalize text for comparison.

        Args:
            text: Text to normalize

        Returns:
            Normalized text
        """
        import re

        # Convert to lowercase
        text = text.lower()

        # Remove punctuation
        text = re.sub(r'[^\w\s]', '', text)

        # Normalize whitespace
        text = ' '.join(text.split())

        return text

    def get_word_alignment(
        self,
        original: str,
        transcribed: str
    ) -> dict:
        """
        Get detailed word-by-word alignment and differences.

        Args:
            original: Original text
            transcribed: Transcribed text

        Returns:
            Dictionary with alignment details
        """
        original_words = self._normalize_text(original).split()
        transcribed_words = self._normalize_text(transcribed).split()

        # Simple word alignment (could be improved with more sophisticated algorithm)
        matches = 0
        mismatches = []

        for i, word in enumerate(original_words):
            if i < len(transcribed_words):
                if word == transcribed_words[i]:
                    matches += 1
                else:
                    mismatches.append({
                        'position': i,
                        'expected': word,
                        'actual': transcribed_words[i]
                    })
            else:
                mismatches.append({
                    'position': i,
                    'expected': word,
                    'actual': '<missing>'
                })

        # Check for extra words in transcription
        if len(transcribed_words) > len(original_words):
            for i in range(len(original_words), len(transcribed_words)):
                mismatches.append({
                    'position': i,
                    'expected': '<none>',
                    'actual': transcribed_words[i]
                })

        return {
            'total_words': len(original_words),
            'matches': matches,
            'mismatches': mismatches,
            'match_rate': (matches / len(original_words) * 100) if original_words else 0
        }
