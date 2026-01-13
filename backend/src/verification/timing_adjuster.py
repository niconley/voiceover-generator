"""
Timing adjuster module for calculating optimal speed adjustments
to achieve target audio durations.
"""
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class TimingAdjustment:
    """Result of a timing adjustment calculation."""

    new_speed: float
    is_achievable: bool
    deviation: float
    reason: Optional[str] = None


class TimingAdjuster:
    """
    Calculates optimal speed adjustments for ElevenLabs TTS
    to achieve target durations within specified tolerance.
    """

    def __init__(
        self,
        speed_min: float = 0.7,
        speed_max: float = 1.2,
        tolerance: float = 0.3
    ):
        """
        Initialize timing adjuster.

        Args:
            speed_min: Minimum speed multiplier (ElevenLabs constraint)
            speed_max: Maximum speed multiplier (ElevenLabs constraint)
            tolerance: Acceptable deviation in seconds (±tolerance)
        """
        self.speed_min = speed_min
        self.speed_max = speed_max
        self.tolerance = tolerance

        logger.info(
            f"TimingAdjuster initialized: speed range [{speed_min}, {speed_max}], "
            f"tolerance ±{tolerance}s"
        )

    def check_timing(
        self,
        actual_duration: float,
        target_duration: float
    ) -> bool:
        """
        Check if actual duration is within tolerance of target.

        Args:
            actual_duration: Actual audio duration in seconds
            target_duration: Target duration in seconds

        Returns:
            True if within tolerance, False otherwise
        """
        deviation = abs(actual_duration - target_duration)
        is_within_tolerance = deviation <= self.tolerance

        logger.debug(
            f"Timing check: actual={actual_duration:.2f}s, "
            f"target={target_duration:.2f}s, "
            f"deviation={deviation:.2f}s, "
            f"within_tolerance={is_within_tolerance}"
        )

        return is_within_tolerance

    def calculate_adjustment(
        self,
        current_duration: float,
        target_duration: float,
        current_speed: float = 1.0
    ) -> TimingAdjustment:
        """
        Calculate required speed adjustment to achieve target duration.

        The calculation works as follows:
        - If audio is too long, need to speed up (increase speed)
        - If audio is too short, need to slow down (decrease speed)
        - new_speed = current_speed * (current_duration / target_duration)

        Example:
        - Current: 15.5s at speed=1.0
        - Target: 15.0s
        - Adjustment: 15.5/15.0 = 1.033
        - New speed: 1.0 * 1.033 = 1.033 (speed up by 3.3%)

        Args:
            current_duration: Current audio duration in seconds
            target_duration: Target duration in seconds
            current_speed: Current speed setting used for generation

        Returns:
            TimingAdjustment with new_speed and achievability status
        """
        if target_duration <= 0:
            return TimingAdjustment(
                new_speed=current_speed,
                is_achievable=False,
                deviation=0,
                reason="Target duration must be positive"
            )

        if current_duration <= 0:
            return TimingAdjustment(
                new_speed=current_speed,
                is_achievable=False,
                deviation=0,
                reason="Current duration must be positive"
            )

        # Calculate deviation
        deviation = abs(current_duration - target_duration)

        # Check if already within tolerance
        if deviation <= self.tolerance:
            logger.info(
                f"Duration already within tolerance: "
                f"deviation={deviation:.2f}s <= {self.tolerance}s"
            )
            return TimingAdjustment(
                new_speed=current_speed,
                is_achievable=True,
                deviation=deviation,
                reason="Already within tolerance"
            )

        # Calculate required speed adjustment
        # If current is longer than target, need to speed up (multiply by >1)
        # If current is shorter than target, need to slow down (multiply by <1)
        speed_factor = current_duration / target_duration
        new_speed = current_speed * speed_factor

        # Check if achievable within ElevenLabs constraints
        if self.speed_min <= new_speed <= self.speed_max:
            logger.info(
                f"Calculated achievable speed adjustment: "
                f"current_duration={current_duration:.2f}s, "
                f"target={target_duration:.2f}s, "
                f"current_speed={current_speed:.2f}, "
                f"new_speed={new_speed:.2f}"
            )
            return TimingAdjustment(
                new_speed=new_speed,
                is_achievable=True,
                deviation=deviation,
                reason=None
            )
        else:
            # Clamp to nearest boundary
            clamped_speed = max(self.speed_min, min(self.speed_max, new_speed))

            # Calculate estimated duration with clamped speed
            estimated_duration = current_duration / (clamped_speed / current_speed)
            estimated_deviation = abs(estimated_duration - target_duration)

            reason = (
                f"Required speed {new_speed:.2f} outside bounds "
                f"[{self.speed_min}, {self.speed_max}]. "
                f"Clamped to {clamped_speed:.2f}. "
                f"Estimated deviation: {estimated_deviation:.2f}s"
            )

            logger.warning(reason)

            # Check if clamped speed will still be within tolerance
            is_achievable = estimated_deviation <= self.tolerance

            return TimingAdjustment(
                new_speed=clamped_speed,
                is_achievable=is_achievable,
                deviation=estimated_deviation,
                reason=reason
            )

    def estimate_duration(
        self,
        text: str,
        speed: float = 1.0,
        words_per_second: float = 2.5
    ) -> float:
        """
        Estimate duration based on word count and speed.

        This is a rough estimate for planning purposes.
        Actual duration will vary based on voice, pauses, etc.

        Args:
            text: Text to be synthesized
            speed: Speed multiplier
            words_per_second: Average words per second at speed=1.0

        Returns:
            Estimated duration in seconds
        """
        word_count = len(text.split())
        base_duration = word_count / words_per_second
        estimated_duration = base_duration / speed

        logger.debug(
            f"Duration estimate: {word_count} words, "
            f"speed={speed:.2f}, "
            f"estimated={estimated_duration:.2f}s"
        )

        return estimated_duration

    def suggest_text_modifications(
        self,
        text: str,
        current_duration: float,
        target_duration: float
    ) -> list[str]:
        """
        Suggest text modifications when timing is impossible to achieve
        through speed adjustment alone.

        Args:
            text: Original text
            current_duration: Current audio duration
            target_duration: Target duration

        Returns:
            List of suggestions for modifying the text
        """
        suggestions = []
        ratio = current_duration / target_duration

        if ratio > 1.2:
            # Audio is too long
            excess_percent = (ratio - 1) * 100
            suggestions.append(
                f"Audio is {excess_percent:.1f}% too long. "
                f"Consider shortening the script."
            )
            suggestions.append(
                f"Remove approximately {len(text.split()) * (ratio - 1) / ratio:.0f} words."
            )
        elif ratio < 0.7:
            # Audio is too short
            shortage_percent = (1 - ratio) * 100
            suggestions.append(
                f"Audio is {shortage_percent:.1f}% too short. "
                f"Consider adding more content to the script."
            )
            suggestions.append(
                f"Add approximately {len(text.split()) * (1 - ratio) / ratio:.0f} words."
            )

        return suggestions

    def get_deviation_percentage(
        self,
        actual_duration: float,
        target_duration: float
    ) -> float:
        """
        Calculate percentage deviation from target duration.

        Args:
            actual_duration: Actual audio duration
            target_duration: Target duration

        Returns:
            Percentage deviation (positive or negative)
        """
        if target_duration == 0:
            return 0.0

        return ((actual_duration - target_duration) / target_duration) * 100
