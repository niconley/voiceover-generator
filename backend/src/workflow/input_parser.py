"""
Input parser for CSV/Excel files containing voiceover scripts and settings.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Tuple
import logging

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class VoiceoverItem:
    """Represents a single voiceover generation task."""

    script_text: str
    target_duration: float
    output_filename: str

    # Optional voice settings
    voice_id: Optional[str] = None
    voice_name: Optional[str] = None
    stability: float = 0.5
    similarity_boost: float = 0.75
    style: float = 0.0
    speed: float = 1.0
    notes: Optional[str] = None

    # Note: V3 prompting uses inline audio tags in the script_text itself
    # Examples: [happy], [whispers], [nervously], [excited], [sad], [laughs]

    # Metadata
    row_number: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Check if the item has no validation errors."""
        return len(self.errors) == 0

    def __str__(self) -> str:
        return (
            f"VoiceoverItem(row={self.row_number}, "
            f"filename='{self.output_filename}', "
            f"duration={self.target_duration}s, "
            f"valid={self.is_valid})"
        )


class InputParser:
    """
    Parser for CSV/Excel files containing voiceover generation tasks.
    """

    REQUIRED_COLUMNS = ["script_text", "target_duration", "output_filename"]

    OPTIONAL_COLUMNS = [
        "voice_id",
        "voice_name",
        "stability",
        "similarity_boost",
        "style",
        "speed",
        "notes"
    ]

    def __init__(self):
        """Initialize input parser."""
        logger.info("InputParser initialized")

    def parse_file(self, file_path: str) -> Tuple[List[VoiceoverItem], List[str]]:
        """
        Parse CSV or Excel file.

        Args:
            file_path: Path to CSV or Excel file

        Returns:
            Tuple of (list of VoiceoverItem objects, list of critical errors)

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file format is unsupported
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Input file not found: {file_path}")

        logger.info(f"Parsing input file: {file_path}")

        # Determine file type and load
        if file_path.suffix.lower() == '.csv':
            df = pd.read_csv(file_path)
        elif file_path.suffix.lower() in ['.xlsx', '.xls']:
            df = pd.read_excel(file_path)
        else:
            raise ValueError(
                f"Unsupported file format: {file_path.suffix}. "
                f"Supported formats: .csv, .xlsx, .xls"
            )

        logger.info(f"Loaded {len(df)} rows from {file_path}")

        # Validate columns
        critical_errors = self._validate_columns(df)
        if critical_errors:
            logger.error(f"Column validation failed: {critical_errors}")
            return [], critical_errors

        # Parse rows
        items = []
        for idx, row in df.iterrows():
            item = self._parse_row(row, idx + 2)  # +2 for header row and 1-indexing
            items.append(item)

            if not item.is_valid:
                logger.warning(f"Row {item.row_number} has validation errors: {item.errors}")

        valid_count = sum(1 for item in items if item.is_valid)
        logger.info(
            f"Parsed {len(items)} items: {valid_count} valid, "
            f"{len(items) - valid_count} with errors"
        )

        return items, []

    def _validate_columns(self, df: pd.DataFrame) -> List[str]:
        """
        Validate that required columns are present.

        Args:
            df: DataFrame to validate

        Returns:
            List of error messages (empty if valid)
        """
        errors = []
        missing_columns = []

        for col in self.REQUIRED_COLUMNS:
            if col not in df.columns:
                missing_columns.append(col)

        if missing_columns:
            errors.append(
                f"Missing required columns: {', '.join(missing_columns)}. "
                f"Required: {', '.join(self.REQUIRED_COLUMNS)}"
            )

        return errors

    def _parse_row(self, row: pd.Series, row_number: int) -> VoiceoverItem:
        """
        Parse a single row into a VoiceoverItem.

        Args:
            row: Pandas Series representing one row
            row_number: Row number for error reporting

        Returns:
            VoiceoverItem (may contain validation errors)
        """
        errors = []

        # Extract required fields
        script_text = self._get_string_value(row, "script_text", errors)
        target_duration = self._get_float_value(row, "target_duration", errors)
        output_filename = self._get_string_value(row, "output_filename", errors)

        # Extract optional fields
        voice_id = self._get_optional_string(row, "voice_id")
        voice_name = self._get_optional_string(row, "voice_name")
        stability = self._get_float_value(row, "stability", errors, default=0.5)
        similarity_boost = self._get_float_value(
            row, "similarity_boost", errors, default=0.75
        )
        style = self._get_float_value(row, "style", errors, default=0.0)
        speed = self._get_float_value(row, "speed", errors, default=1.0)
        notes = self._get_optional_string(row, "notes")

        # Validation
        if script_text and not script_text.strip():
            errors.append("script_text cannot be empty")

        if target_duration is not None and target_duration <= 0:
            errors.append(f"target_duration must be positive (got {target_duration})")

        if output_filename and not output_filename.strip():
            errors.append("output_filename cannot be empty")

        if stability is not None and not (0 <= stability <= 1):
            errors.append(f"stability must be between 0 and 1 (got {stability})")

        if similarity_boost is not None and not (0 <= similarity_boost <= 1):
            errors.append(
                f"similarity_boost must be between 0 and 1 (got {similarity_boost})"
            )

        if style is not None and not (0 <= style <= 1):
            errors.append(f"style must be between 0 and 1 (got {style})")

        if speed is not None and not (0.25 <= speed <= 2.0):
            errors.append(f"speed must be between 0.25 and 2.0 (got {speed})")

        if not voice_id and not voice_name:
            errors.append("Either voice_id or voice_name must be provided")

        # Create item
        item = VoiceoverItem(
            script_text=script_text or "",
            target_duration=target_duration or 0.0,
            output_filename=output_filename or "",
            voice_id=voice_id,
            voice_name=voice_name,
            stability=stability or 0.5,
            similarity_boost=similarity_boost or 0.75,
            style=style or 0.0,
            speed=speed or 1.0,
            notes=notes,
            row_number=row_number,
            errors=errors
        )

        return item

    def _get_string_value(
        self,
        row: pd.Series,
        column: str,
        errors: List[str]
    ) -> Optional[str]:
        """
        Extract string value from row.

        Args:
            row: Pandas Series
            column: Column name
            errors: List to append errors to

        Returns:
            String value or None if missing/invalid
        """
        if column not in row or pd.isna(row[column]):
            errors.append(f"Missing required field: {column}")
            return None

        value = str(row[column]).strip()
        return value if value else None

    def _get_float_value(
        self,
        row: pd.Series,
        column: str,
        errors: List[str],
        default: Optional[float] = None
    ) -> Optional[float]:
        """
        Extract float value from row.

        Args:
            row: Pandas Series
            column: Column name
            errors: List to append errors to
            default: Default value if column is optional

        Returns:
            Float value, default, or None if invalid
        """
        if column not in row or pd.isna(row[column]):
            if default is not None:
                return default
            errors.append(f"Missing required field: {column}")
            return None

        try:
            return float(row[column])
        except (ValueError, TypeError):
            errors.append(f"Invalid number for {column}: {row[column]}")
            return default

    def _get_optional_string(
        self,
        row: pd.Series,
        column: str
    ) -> Optional[str]:
        """
        Extract optional string value from row.

        Args:
            row: Pandas Series
            column: Column name

        Returns:
            String value or None if missing
        """
        if column not in row or pd.isna(row[column]):
            return None

        value = str(row[column]).strip()
        return value if value else None

    def validate_file(self, file_path: str) -> Tuple[bool, List[str], Dict]:
        """
        Validate input file without parsing all rows.

        Args:
            file_path: Path to CSV or Excel file

        Returns:
            Tuple of (is_valid, errors, summary_stats)
        """
        try:
            items, critical_errors = self.parse_file(file_path)

            if critical_errors:
                return False, critical_errors, {}

            valid_items = [item for item in items if item.is_valid]
            invalid_items = [item for item in items if not item.is_valid]

            # Collect all errors
            all_errors = []
            for item in invalid_items:
                for error in item.errors:
                    all_errors.append(f"Row {item.row_number}: {error}")

            summary = {
                "total_items": len(items),
                "valid_items": len(valid_items),
                "invalid_items": len(invalid_items),
                "total_duration": sum(item.target_duration for item in valid_items),
            }

            is_valid = len(invalid_items) == 0

            logger.info(
                f"File validation: {summary['valid_items']}/{summary['total_items']} valid"
            )

            return is_valid, all_errors, summary

        except Exception as e:
            logger.error(f"File validation failed: {e}")
            return False, [str(e)], {}

    def get_summary(self, items: List[VoiceoverItem]) -> Dict:
        """
        Get summary statistics for a list of items.

        Args:
            items: List of VoiceoverItem objects

        Returns:
            Dictionary with summary statistics
        """
        valid_items = [item for item in items if item.is_valid]

        return {
            "total_items": len(items),
            "valid_items": len(valid_items),
            "invalid_items": len(items) - len(valid_items),
            "total_duration": sum(item.target_duration for item in valid_items),
            "avg_duration": (
                sum(item.target_duration for item in valid_items) / len(valid_items)
                if valid_items else 0
            ),
            "min_duration": (
                min(item.target_duration for item in valid_items)
                if valid_items else 0
            ),
            "max_duration": (
                max(item.target_duration for item in valid_items)
                if valid_items else 0
            ),
        }
