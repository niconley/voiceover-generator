"""
Output manager for organizing generated files and creating reports.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
import logging
import shutil
import json

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class GenerationResult:
    """Result of a single voiceover generation."""

    filename: str
    status: str  # 'completed', 'failed', 'needs_review'
    attempts: int
    final_duration: Optional[float] = None
    target_duration: Optional[float] = None
    duration_diff: Optional[float] = None
    quality_passed: bool = False
    verification_accuracy: Optional[float] = None
    issues: List[str] = field(default_factory=list)
    notes: str = ""
    audio_path: Optional[Path] = None
    error: Optional[str] = None

    # LLM Quality Control fields
    llm_qc_status: Optional[str] = None  # 'pass', 'flag', 'fail', or None if not checked
    llm_qc_score: Optional[float] = None  # 0-100 quality score
    llm_qc_issues: List[str] = field(default_factory=list)
    llm_qc_guidance: Optional[str] = None  # Regeneration guidance if failed

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'filename': self.filename,
            'status': self.status,
            'attempts': self.attempts,
            'final_duration': self.final_duration,
            'target_duration': self.target_duration,
            'duration_diff': self.duration_diff,
            'quality_passed': self.quality_passed,
            'verification_accuracy': self.verification_accuracy,
            'issues': '; '.join(self.issues) if self.issues else '',
            'notes': self.notes,
            'error': self.error,
            'llm_qc_status': self.llm_qc_status,
            'llm_qc_score': self.llm_qc_score,
            'llm_qc_issues': self.llm_qc_issues,  # Keep as array for web UI
            'llm_qc_guidance': self.llm_qc_guidance
        }


@dataclass
class BatchResult:
    """Result of a batch generation."""

    batch_id: str
    input_file: str
    timestamp: datetime
    results: List[GenerationResult] = field(default_factory=list)
    total_items: int = 0
    completed_items: int = 0
    failed_items: int = 0
    review_items: int = 0
    total_duration: float = 0.0

    def add_result(self, result: GenerationResult):
        """Add a generation result and update counts."""
        self.results.append(result)

        if result.status == 'completed':
            self.completed_items += 1
        elif result.status == 'failed':
            self.failed_items += 1
        elif result.status == 'needs_review':
            self.review_items += 1

        if result.final_duration:
            self.total_duration += result.final_duration

    def get_summary(self) -> str:
        """Get human-readable summary."""
        success_rate = (
            (self.completed_items / self.total_items * 100)
            if self.total_items > 0
            else 0
        )

        summary = f"""
=== Voiceover Generation Report ===
Batch ID: {self.batch_id}
Input File: {self.input_file}
Date: {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}
Total Items: {self.total_items}

Results:
  ✓ Completed: {self.completed_items} ({self.completed_items / self.total_items * 100:.1f}%)
  ✗ Failed: {self.failed_items} ({self.failed_items / self.total_items * 100:.1f}%)
  ⚠ Needs Review: {self.review_items} ({self.review_items / self.total_items * 100:.1f}%)

Success Rate: {success_rate:.1f}%
Total Duration: {self.total_duration:.1f}s
        """.strip()

        return summary


class OutputManager:
    """
    Manages output organization, file movement, and report generation.
    """

    def __init__(
        self,
        output_dir: Path,
        completed_dir: Optional[Path] = None,
        failed_dir: Optional[Path] = None,
        needs_review_dir: Optional[Path] = None,
        logs_dir: Optional[Path] = None
    ):
        """
        Initialize output manager.

        Args:
            output_dir: Base output directory
            completed_dir: Directory for completed files
            failed_dir: Directory for failed files
            needs_review_dir: Directory for files needing review
            logs_dir: Directory for log files and reports
        """
        self.output_dir = Path(output_dir)
        self.completed_dir = Path(completed_dir) if completed_dir else self.output_dir / "completed"
        self.failed_dir = Path(failed_dir) if failed_dir else self.output_dir / "failed"
        self.needs_review_dir = Path(needs_review_dir) if needs_review_dir else self.output_dir / "needs_review"
        self.logs_dir = Path(logs_dir) if logs_dir else Path("logs")

        # Ensure directories exist
        self._create_directories()

        logger.info(f"OutputManager initialized: {self.output_dir}")

    def _create_directories(self):
        """Create output directories if they don't exist."""
        for directory in [
            self.completed_dir,
            self.failed_dir,
            self.needs_review_dir,
            self.logs_dir
        ]:
            directory.mkdir(parents=True, exist_ok=True)

    def organize_output(
        self,
        result: GenerationResult,
        source_path: Path
    ) -> Path:
        """
        Move generated file to appropriate output folder based on status.

        Args:
            result: Generation result with status
            source_path: Current location of the file

        Returns:
            Final path of the file

        Raises:
            IOError: If file cannot be moved
        """
        # Determine destination directory
        if result.status == 'completed':
            dest_dir = self.completed_dir
        elif result.status == 'failed':
            dest_dir = self.failed_dir
        else:  # needs_review
            dest_dir = self.needs_review_dir

        dest_path = dest_dir / result.filename

        try:
            # Move file
            if source_path.exists():
                shutil.move(str(source_path), str(dest_path))
                logger.info(f"Moved {result.filename} to {dest_dir.name}/")
            else:
                logger.warning(f"Source file not found: {source_path}")
                return dest_path

            return dest_path

        except Exception as e:
            logger.error(f"Failed to move {result.filename}: {e}")
            raise IOError(f"Cannot organize output file: {e}")

    def save_audio(
        self,
        audio_data: bytes,
        filename: str,
        status: str = 'completed'
    ) -> Path:
        """
        Save audio data directly to appropriate folder.

        Args:
            audio_data: Audio data as bytes
            filename: Output filename
            status: Status ('completed', 'failed', 'needs_review')

        Returns:
            Path to saved file
        """
        # Determine destination directory
        if status == 'completed':
            dest_dir = self.completed_dir
        elif status == 'failed':
            dest_dir = self.failed_dir
        else:
            dest_dir = self.needs_review_dir

        dest_path = dest_dir / filename

        try:
            with open(dest_path, 'wb') as f:
                f.write(audio_data)

            logger.info(f"Saved audio: {dest_path}")
            return dest_path

        except Exception as e:
            logger.error(f"Failed to save audio {filename}: {e}")
            raise IOError(f"Cannot save audio file: {e}")

    def generate_report(
        self,
        batch_result: BatchResult,
        format: str = 'csv'
    ) -> Path:
        """
        Generate detailed report for batch results.

        Args:
            batch_result: Batch result to report on
            format: Report format ('csv', 'json', 'txt')

        Returns:
            Path to generated report
        """
        timestamp = batch_result.timestamp.strftime('%Y%m%d_%H%M%S')
        report_name = f"report_{batch_result.batch_id}_{timestamp}"

        if format == 'csv':
            return self._generate_csv_report(batch_result, report_name)
        elif format == 'json':
            return self._generate_json_report(batch_result, report_name)
        else:
            return self._generate_text_report(batch_result, report_name)

    def _generate_csv_report(
        self,
        batch_result: BatchResult,
        report_name: str
    ) -> Path:
        """Generate CSV report."""
        report_path = self.logs_dir / f"{report_name}.csv"

        # Convert results to DataFrame
        data = [result.to_dict() for result in batch_result.results]
        df = pd.DataFrame(data)

        # Save to CSV
        df.to_csv(report_path, index=False)

        logger.info(f"Generated CSV report: {report_path}")
        return report_path

    def _generate_json_report(
        self,
        batch_result: BatchResult,
        report_name: str
    ) -> Path:
        """Generate JSON report."""
        report_path = self.logs_dir / f"{report_name}.json"

        report_data = {
            'batch_id': batch_result.batch_id,
            'input_file': batch_result.input_file,
            'timestamp': batch_result.timestamp.isoformat(),
            'summary': {
                'total_items': batch_result.total_items,
                'completed': batch_result.completed_items,
                'failed': batch_result.failed_items,
                'needs_review': batch_result.review_items,
                'total_duration': batch_result.total_duration
            },
            'results': [result.to_dict() for result in batch_result.results]
        }

        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, indent=2)

        logger.info(f"Generated JSON report: {report_path}")
        return report_path

    def _generate_text_report(
        self,
        batch_result: BatchResult,
        report_name: str
    ) -> Path:
        """Generate text report."""
        report_path = self.logs_dir / f"{report_name}.txt"

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(batch_result.get_summary())
            f.write("\n\n=== Detailed Results ===\n\n")

            for result in batch_result.results:
                f.write(f"File: {result.filename}\n")
                f.write(f"Status: {result.status}\n")
                f.write(f"Attempts: {result.attempts}\n")

                if result.final_duration:
                    f.write(f"Duration: {result.final_duration:.2f}s ")
                    f.write(f"(target: {result.target_duration:.2f}s, ")
                    f.write(f"diff: {result.duration_diff:+.2f}s)\n")

                if result.verification_accuracy:
                    f.write(f"Verification: {result.verification_accuracy:.1f}%\n")

                if result.issues:
                    f.write(f"Issues: {'; '.join(result.issues)}\n")

                if result.error:
                    f.write(f"Error: {result.error}\n")

                f.write("\n")

        logger.info(f"Generated text report: {report_path}")
        return report_path

    def create_batch_archive(
        self,
        batch_result: BatchResult,
        include_failed: bool = False
    ) -> Path:
        """
        Create a zip archive of all files in the batch.

        Args:
            batch_result: Batch result
            include_failed: Whether to include failed files

        Returns:
            Path to zip archive
        """
        import zipfile

        timestamp = batch_result.timestamp.strftime('%Y%m%d_%H%M%S')
        archive_name = f"batch_{batch_result.batch_id}_{timestamp}.zip"
        archive_path = self.output_dir / archive_name

        try:
            with zipfile.ZipFile(archive_path, 'w') as zipf:
                # Add completed files
                for file in self.completed_dir.glob('*.mp3'):
                    zipf.write(file, f"completed/{file.name}")

                # Add needs_review files
                for file in self.needs_review_dir.glob('*.mp3'):
                    zipf.write(file, f"needs_review/{file.name}")

                # Add failed files if requested
                if include_failed:
                    for file in self.failed_dir.glob('*.mp3'):
                        zipf.write(file, f"failed/{file.name}")

                # Add report
                report_path = self.generate_report(batch_result, format='csv')
                zipf.write(report_path, f"report.csv")

            logger.info(f"Created batch archive: {archive_path}")
            return archive_path

        except Exception as e:
            logger.error(f"Failed to create archive: {e}")
            raise IOError(f"Cannot create archive: {e}")

    def clean_output_directories(self):
        """Remove all files from output directories."""
        for directory in [self.completed_dir, self.failed_dir, self.needs_review_dir]:
            for file in directory.glob('*.mp3'):
                file.unlink()
                logger.debug(f"Deleted: {file}")

        logger.info("Cleaned output directories")

    def get_directory_stats(self) -> Dict:
        """
        Get statistics about output directories.

        Returns:
            Dictionary with file counts and sizes
        """
        stats = {}

        for name, directory in [
            ('completed', self.completed_dir),
            ('failed', self.failed_dir),
            ('needs_review', self.needs_review_dir)
        ]:
            files = list(directory.glob('*.mp3'))
            total_size = sum(f.stat().st_size for f in files)

            stats[name] = {
                'count': len(files),
                'size_bytes': total_size,
                'size_mb': total_size / (1024 * 1024)
            }

        return stats
