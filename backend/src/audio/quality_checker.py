"""
Audio quality checker for detecting clipping, silence, and distortion.
"""
from dataclasses import dataclass, field
from io import BytesIO
from typing import List, Dict, Union, Optional
from pathlib import Path
import logging

import numpy as np
from pydub import AudioSegment
from pydub.silence import detect_silence

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    """Result of a single quality check."""

    name: str
    passed: bool
    value: float
    threshold: float
    details: str = ""

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"{self.name}: {status} (value={self.value:.3f}, threshold={self.threshold:.3f})"


@dataclass
class QualityReport:
    """Comprehensive quality report for an audio file."""

    checks: List[CheckResult] = field(default_factory=list)
    passed: bool = True
    issues: List[str] = field(default_factory=list)

    def __post_init__(self):
        """Update passed status and issues after initialization."""
        self.passed = all(check.passed for check in self.checks)
        self.issues = [
            check.details
            for check in self.checks
            if not check.passed and check.details
        ]

    def get_summary(self) -> str:
        """Get human-readable summary."""
        status = "PASSED" if self.passed else "FAILED"
        failed_checks = [check.name for check in self.checks if not check.passed]

        summary = f"Quality Check: {status}\n"
        if failed_checks:
            summary += f"Failed checks: {', '.join(failed_checks)}\n"
        summary += f"Issues: {len(self.issues)}"

        return summary

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "passed": self.passed,
            "checks": [
                {
                    "name": check.name,
                    "passed": check.passed,
                    "value": check.value,
                    "threshold": check.threshold,
                    "details": check.details
                }
                for check in self.checks
            ],
            "issues": self.issues
        }


class QualityChecker:
    """
    Performs comprehensive quality checks on audio files:
    - Clipping detection
    - Silence detection
    - Distortion detection
    """

    def __init__(
        self,
        clipping_threshold: float = 0.99,
        max_clipping_percentage: float = 0.5,
        silence_threshold_db: float = -50.0,
        max_silence_ratio: float = 0.1,
        min_silence_len: int = 300,
        distortion_zcr_threshold: float = 0.8
    ):
        """
        Initialize quality checker.

        Args:
            clipping_threshold: Amplitude threshold for clipping (0-1)
            max_clipping_percentage: Maximum acceptable clipping percentage
            silence_threshold_db: Silence threshold in dBFS
            max_silence_ratio: Maximum acceptable silence ratio (0-1)
            min_silence_len: Minimum silence length to detect (ms)
            distortion_zcr_threshold: Zero-crossing rate threshold for distortion
        """
        self.clipping_threshold = clipping_threshold
        self.max_clipping_percentage = max_clipping_percentage
        self.silence_threshold_db = silence_threshold_db
        self.max_silence_ratio = max_silence_ratio
        self.min_silence_len = min_silence_len
        self.distortion_zcr_threshold = distortion_zcr_threshold

        logger.info("QualityChecker initialized with default thresholds")

    def run_all_checks(
        self,
        audio_data: Union[bytes, str, Path],
        metadata: Optional[Dict] = None
    ) -> QualityReport:
        """
        Run all quality checks on audio.

        Args:
            audio_data: Audio data as bytes or file path
            metadata: Additional metadata for checks

        Returns:
            QualityReport with results of all checks
        """
        metadata = metadata or {}
        checks = []

        logger.info("Running quality checks")

        # Load audio
        try:
            if isinstance(audio_data, bytes):
                audio = AudioSegment.from_file(BytesIO(audio_data))
            else:
                audio = AudioSegment.from_file(str(audio_data))
        except Exception as e:
            logger.error(f"Failed to load audio for quality checks: {e}")
            return QualityReport(
                checks=[],
                passed=False,
                issues=[f"Failed to load audio: {e}"]
            )

        # Run individual checks
        checks.append(self.check_clipping(audio))
        checks.append(self.check_silence(audio))
        checks.append(self.check_distortion(audio))

        report = QualityReport(checks=checks)
        logger.info(f"Quality checks completed: {report.get_summary()}")

        return report

    def check_clipping(self, audio: AudioSegment) -> CheckResult:
        """
        Check for audio clipping.

        Args:
            audio: AudioSegment to check

        Returns:
            CheckResult with clipping percentage
        """
        try:
            # Get audio samples as numpy array
            samples = np.array(audio.get_array_of_samples())

            # Normalize to -1 to 1 range
            max_value = 2 ** (audio.sample_width * 8 - 1)
            normalized = samples.astype(float) / max_value

            # Count clipped samples
            clipped = np.sum(np.abs(normalized) > self.clipping_threshold)
            total = len(samples)
            percentage = (clipped / total) * 100

            passed = percentage <= self.max_clipping_percentage

            details = (
                f"Clipped samples: {clipped}/{total} ({percentage:.2f}%)"
                if not passed
                else ""
            )

            logger.debug(
                f"Clipping check: {percentage:.2f}% "
                f"(threshold: {self.max_clipping_percentage}%)"
            )

            return CheckResult(
                name="clipping",
                passed=passed,
                value=percentage,
                threshold=self.max_clipping_percentage,
                details=details
            )

        except Exception as e:
            logger.error(f"Clipping check failed: {e}")
            return CheckResult(
                name="clipping",
                passed=False,
                value=0.0,
                threshold=self.max_clipping_percentage,
                details=f"Check failed: {e}"
            )

    def check_silence(self, audio: AudioSegment) -> CheckResult:
        """
        Check for excessive silence.

        Args:
            audio: AudioSegment to check

        Returns:
            CheckResult with silence ratio
        """
        try:
            # Detect silent segments
            silent_ranges = detect_silence(
                audio,
                min_silence_len=self.min_silence_len,
                silence_thresh=self.silence_threshold_db
            )

            # Calculate total silence duration
            total_silence_ms = sum(end - start for start, end in silent_ranges)
            total_duration_ms = len(audio)

            silence_ratio = total_silence_ms / total_duration_ms if total_duration_ms > 0 else 0
            passed = silence_ratio <= self.max_silence_ratio

            details = (
                f"Excessive silence detected: {silence_ratio * 100:.1f}% "
                f"({total_silence_ms}ms / {total_duration_ms}ms)"
                if not passed
                else ""
            )

            logger.debug(
                f"Silence check: {silence_ratio * 100:.1f}% "
                f"(threshold: {self.max_silence_ratio * 100}%)"
            )

            return CheckResult(
                name="silence",
                passed=passed,
                value=silence_ratio,
                threshold=self.max_silence_ratio,
                details=details
            )

        except Exception as e:
            logger.error(f"Silence check failed: {e}")
            return CheckResult(
                name="silence",
                passed=False,
                value=0.0,
                threshold=self.max_silence_ratio,
                details=f"Check failed: {e}"
            )

    def check_distortion(self, audio: AudioSegment) -> CheckResult:
        """
        Check for audio distortion using zero-crossing rate.

        High ZCR can indicate distortion or noise.

        Args:
            audio: AudioSegment to check

        Returns:
            CheckResult with ZCR score
        """
        try:
            # Get audio samples
            samples = np.array(audio.get_array_of_samples())

            # Calculate zero-crossing rate
            zero_crossings = np.sum(np.abs(np.diff(np.sign(samples))))
            zcr = zero_crossings / len(samples)

            # Normalize ZCR (typical range is 0-0.5 for clean audio)
            normalized_zcr = zcr / 0.5

            passed = normalized_zcr <= self.distortion_zcr_threshold

            details = (
                f"High zero-crossing rate detected: {normalized_zcr:.3f} "
                f"(may indicate distortion or noise)"
                if not passed
                else ""
            )

            logger.debug(
                f"Distortion check: ZCR={normalized_zcr:.3f} "
                f"(threshold: {self.distortion_zcr_threshold})"
            )

            return CheckResult(
                name="distortion",
                passed=passed,
                value=normalized_zcr,
                threshold=self.distortion_zcr_threshold,
                details=details
            )

        except Exception as e:
            logger.error(f"Distortion check failed: {e}")
            return CheckResult(
                name="distortion",
                passed=False,
                value=0.0,
                threshold=self.distortion_zcr_threshold,
                details=f"Check failed: {e}"
            )

    def check_sample_rate(
        self,
        audio: AudioSegment,
        expected_rate: int = 44100
    ) -> CheckResult:
        """
        Check if audio sample rate matches expected value.

        Args:
            audio: AudioSegment to check
            expected_rate: Expected sample rate in Hz

        Returns:
            CheckResult with sample rate match
        """
        actual_rate = audio.frame_rate
        passed = actual_rate == expected_rate

        details = (
            f"Sample rate mismatch: {actual_rate}Hz (expected: {expected_rate}Hz)"
            if not passed
            else ""
        )

        return CheckResult(
            name="sample_rate",
            passed=passed,
            value=float(actual_rate),
            threshold=float(expected_rate),
            details=details
        )

    def get_audio_metrics(
        self,
        audio_data: Union[bytes, str, Path]
    ) -> Dict:
        """
        Get detailed audio metrics without pass/fail evaluation.

        Args:
            audio_data: Audio data as bytes or file path

        Returns:
            Dictionary with various audio metrics
        """
        try:
            if isinstance(audio_data, bytes):
                audio = AudioSegment.from_file(BytesIO(audio_data))
            else:
                audio = AudioSegment.from_file(str(audio_data))

            samples = np.array(audio.get_array_of_samples())
            max_value = 2 ** (audio.sample_width * 8 - 1)
            normalized = samples.astype(float) / max_value

            metrics = {
                "duration_seconds": audio.duration_seconds,
                "sample_rate": audio.frame_rate,
                "channels": audio.channels,
                "sample_width": audio.sample_width,
                "frame_count": audio.frame_count(),
                "dBFS": audio.dBFS,
                "max_dBFS": audio.max_dBFS,
                "rms": audio.rms,
                "peak_amplitude": np.max(np.abs(normalized)),
                "mean_amplitude": np.mean(np.abs(normalized)),
            }

            logger.debug(f"Audio metrics: {metrics}")
            return metrics

        except Exception as e:
            logger.error(f"Failed to get audio metrics: {e}")
            return {}
