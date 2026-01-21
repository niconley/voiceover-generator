"""
Main workflow orchestrator for coordinating voiceover generation.
"""
from pathlib import Path
from typing import Optional, Callable
from datetime import datetime
import logging
import uuid
import tempfile

from backend.config.settings import Config
from backend.src.api.elevenlabs_client import ElevenLabsClient
from backend.src.api.retry_strategy import RetryStrategy
from backend.src.audio.processor import AudioProcessor
from backend.src.audio.quality_checker import QualityChecker
from backend.src.verification.timing_adjuster import TimingAdjuster
from backend.src.verification.speech_verifier import SpeechVerifier
from backend.src.verification.llm_quality_checker import LLMQualityChecker
from backend.src.verification.gemini_audio_qc import GeminiAudioQC
from backend.src.workflow.input_parser import InputParser, VoiceoverItem
from backend.src.workflow.output_manager import OutputManager, GenerationResult, BatchResult
from backend.src.utils.logger import ProgressLogger

logger = logging.getLogger(__name__)


class VoiceoverOrchestrator:
    """
    Main orchestrator for bulk voiceover generation workflow.

    Coordinates all components:
    - Input parsing
    - API calls to ElevenLabs
    - Audio processing and timing adjustments
    - Quality checks
    - Speech verification
    - Output organization and reporting
    """

    def __init__(self, config: Optional[Config] = None):
        """
        Initialize orchestrator with all components.

        Args:
            config: Configuration object (uses default if None)
        """
        self.config = config or Config()

        # Validate configuration
        is_valid, errors = self.config.validate()
        if not is_valid:
            raise ValueError(f"Invalid configuration: {'; '.join(errors)}")

        # Initialize components
        self.api_client = ElevenLabsClient(
            api_key=self.config.ELEVENLABS_API_KEY,
            default_model=self.config.ELEVENLABS_DEFAULT_MODEL
        )

        self.retry_strategy = RetryStrategy(
            max_retries=self.config.MAX_RETRIES,
            base_delay=self.config.RETRY_BASE_DELAY,
            max_delay=self.config.RETRY_MAX_DELAY,
            retryable_status_codes=self.config.RETRYABLE_STATUS_CODES
        )

        self.audio_processor = AudioProcessor(
            default_format=self.config.AUDIO_FORMAT,
            default_bitrate=self.config.BITRATE
        )

        self.quality_checker = QualityChecker(
            max_clipping_percentage=self.config.MAX_CLIPPING_PERCENTAGE,
            silence_threshold_db=self.config.SILENCE_THRESHOLD_DB,
            max_silence_ratio=self.config.MAX_SILENCE_RATIO
        )

        self.timing_adjuster = TimingAdjuster(
            speed_min=self.config.SPEED_MIN,
            speed_max=self.config.SPEED_MAX,
            tolerance=self.config.DURATION_TOLERANCE
        )

        self.speech_verifier = SpeechVerifier(
            model_name=self.config.WHISPER_MODEL,
            min_accuracy=self.config.MIN_VERIFICATION_ACCURACY
        )

        # Initialize LLM quality checker if enabled (text-based)
        self.llm_qc_enabled = self.config.ENABLE_LLM_QC and self.config.ANTHROPIC_API_KEY
        if self.llm_qc_enabled:
            self.llm_quality_checker = LLMQualityChecker(
                api_key=self.config.ANTHROPIC_API_KEY,
                model=self.config.CLAUDE_MODEL
            )
            logger.info("LLM Quality Control (text-based) enabled")
        else:
            self.llm_quality_checker = None
            if not self.config.ANTHROPIC_API_KEY:
                logger.warning("LLM QC disabled: ANTHROPIC_API_KEY not set")

        # Initialize Gemini audio quality checker if enabled (audio-based)
        self.audio_qc_enabled = self.config.ENABLE_AUDIO_QC and self.config.GOOGLE_API_KEY
        if self.audio_qc_enabled:
            self.gemini_audio_qc = GeminiAudioQC(
                api_key=self.config.GOOGLE_API_KEY,
                model=self.config.GEMINI_MODEL
            )
            logger.info("Audio Quality Control (Gemini) enabled")
        else:
            self.gemini_audio_qc = None
            if not self.config.GOOGLE_API_KEY:
                logger.warning("Audio QC disabled: GOOGLE_API_KEY not set")

        self.input_parser = InputParser()

        self.output_manager = OutputManager(
            output_dir=self.config.OUTPUT_DIR,
            logs_dir=self.config.LOGS_DIR
        )

        logger.info("VoiceoverOrchestrator initialized successfully")

    def process_batch(
        self,
        input_file: str,
        max_retries: Optional[int] = None,
        progress_callback: Optional[Callable] = None
    ) -> BatchResult:
        """
        Process entire batch from CSV/Excel file.

        Args:
            input_file: Path to CSV or Excel input file
            max_retries: Override config max retries
            progress_callback: Optional callback for progress updates

        Returns:
            BatchResult with all generation results

        Raises:
            FileNotFoundError: If input file doesn't exist
            ValueError: If input file is invalid
        """
        logger.info(f"Starting batch processing: {input_file}")

        # Generate batch ID
        batch_id = str(uuid.uuid4())[:8]

        # Parse input file
        items, critical_errors = self.input_parser.parse_file(input_file)

        if critical_errors:
            raise ValueError(f"Invalid input file: {'; '.join(critical_errors)}")

        # Filter out invalid items
        valid_items = [item for item in items if item.is_valid]
        invalid_items = [item for item in items if not item.is_valid]

        if invalid_items:
            logger.warning(
                f"Skipping {len(invalid_items)} invalid items. "
                f"Check logs for details."
            )

        # Create batch result
        batch_result = BatchResult(
            batch_id=batch_id,
            input_file=input_file,
            timestamp=datetime.now(),
            total_items=len(valid_items)
        )

        # Initialize progress logger
        progress = ProgressLogger(
            total_items=len(valid_items),
            logger=logger,
            log_interval=5
        )

        # Process each item
        for item in valid_items:
            logger.info(f"Processing: {item.output_filename}")

            try:
                # Process single item
                result = self.process_single_item(
                    item,
                    max_retries=max_retries
                )

                # Add to batch result
                batch_result.add_result(result)

                # Update progress
                progress.log_progress(
                    success=(result.status == 'completed'),
                    item_name=item.output_filename
                )

                # Call progress callback if provided
                if progress_callback:
                    progress_callback(
                        current=progress.processed_items,
                        total=progress.total_items,
                        item=result
                    )

            except Exception as e:
                logger.error(f"Failed to process {item.output_filename}: {e}")

                # Create failed result
                result = GenerationResult(
                    filename=item.output_filename,
                    status='failed',
                    attempts=0,
                    target_duration=item.target_duration,
                    error=str(e)
                )

                batch_result.add_result(result)
                progress.log_progress(success=False, item_name=item.output_filename)

        # Log final summary
        logger.info(progress.get_summary())
        logger.info(f"\n{batch_result.get_summary()}")

        # Generate report
        self.output_manager.generate_report(batch_result, format='csv')
        self.output_manager.generate_report(batch_result, format='json')

        return batch_result

    def process_single_item(
        self,
        item: VoiceoverItem,
        max_retries: Optional[int] = None
    ) -> GenerationResult:
        """
        Process a single voiceover item with retry logic.

        Args:
            item: VoiceoverItem to process
            max_retries: Override default max retries

        Returns:
            GenerationResult with status and details
        """
        max_retries = max_retries or self.config.MAX_RETRIES
        attempt = 0
        current_speed = item.speed
        issues = []

        # Resolve voice ID if only name provided
        voice_id = item.voice_id
        if not voice_id and item.voice_name:
            voice_id = self.api_client.get_voice_by_name(item.voice_name)
            if not voice_id:
                return GenerationResult(
                    filename=item.output_filename,
                    status='failed',
                    attempts=0,
                    target_duration=item.target_duration,
                    error=f"Voice '{item.voice_name}' not found"
                )

        # Try generation with retries
        original_script_text = item.script_text

        # Track best attempt across all retries
        best_attempt = None
        best_duration_diff = float('inf')

        # Track audio tags suggested by QC for retry
        qc_suggested_tags = []

        while attempt < max_retries:
            attempt += 1

            try:
                # Modify script text with audio tags on retry attempts
                adjusted_script_text = original_script_text
                tags_to_add = []

                if attempt > 1:
                    # Add timing tags based on speed adjustment
                    if current_speed < 1.0:
                        tags_to_add.append("slower")
                    elif current_speed > 1.0:
                        tags_to_add.append("faster")

                    # Add QC-suggested tags from previous Audio QC failure
                    if qc_suggested_tags:
                        for tag in qc_suggested_tags:
                            if tag not in tags_to_add:
                                tags_to_add.append(tag)
                        logger.info(f"Adding QC-suggested audio tags: {qc_suggested_tags}")

                # Apply all tags to script
                if tags_to_add:
                    tags_prefix = ' '.join(f'[{tag}]' for tag in tags_to_add)
                    adjusted_script_text = f"{tags_prefix} {original_script_text}"
                    logger.info(f"Script with audio tags: {tags_prefix} ...")

                logger.info(
                    f"Attempt {attempt}/{max_retries} for {item.output_filename} "
                    f"(speed={current_speed:.2f})"
                )

                # Generate speech with speed parameter + timing guidance tags
                audio_data = self.retry_strategy.execute_with_retry(
                    self.api_client.generate_speech,
                    text=adjusted_script_text,
                    voice_id=voice_id,
                    stability=item.stability,
                    similarity_boost=item.similarity_boost,
                    style=item.style,
                    speed=current_speed
                )

                # Trim silence from beginning and end for accurate timing
                # This happens BEFORE duration check to measure actual voice content
                logger.info("Trimming silence from audio with padding")
                audio_data = self.audio_processor.trim_silence(
                    audio_data,
                    silence_threshold=self.config.SILENCE_THRESHOLD,
                    padding_ms=self.config.SILENCE_PADDING_MS
                )

                # Measure duration of trimmed audio
                actual_duration = self.audio_processor.get_duration(audio_data)

                logger.info(
                    f"Generated audio: {actual_duration:.2f}s "
                    f"(target: {item.target_duration:.2f}s)"
                )

                # Track best attempt by duration accuracy
                duration_diff = abs(actual_duration - item.target_duration)
                if duration_diff < best_duration_diff:
                    best_duration_diff = duration_diff
                    best_attempt = {
                        'audio_data': audio_data,
                        'actual_duration': actual_duration,
                        'attempt_number': attempt,
                        'speed': current_speed
                    }
                    logger.info(f"New best attempt: {duration_diff:.2f}s off target")

                # Check if timing is acceptable
                if self.timing_adjuster.check_timing(actual_duration, item.target_duration):
                    # Timing is good, proceed with quality checks
                    logger.info("Timing acceptable, running quality checks")

                    # Run quality checks
                    quality_report = self.quality_checker.run_all_checks(
                        audio_data,
                        metadata={'target_duration': item.target_duration}
                    )

                    # Run speech verification
                    verification_result = self.speech_verifier.verify_content(
                        original_text=item.script_text,
                        audio_data=audio_data
                    )

                    # Run LLM quality control if enabled
                    llm_qc_result = None
                    if self.llm_qc_enabled and verification_result.transcribed_text:
                        logger.info("Running LLM quality control")
                        llm_qc_result = self.llm_quality_checker.analyze_transcription(
                            original_script=item.script_text,
                            transcription=verification_result.transcribed_text,
                            context={
                                'target_duration': item.target_duration,
                                'notes': item.notes
                            }
                        )

                        # Log LLM QC results
                        logger.info(
                            f"LLM QC: {llm_qc_result.status.upper()} "
                            f"(score: {llm_qc_result.score}/100)"
                        )
                        if llm_qc_result.issues:
                            logger.info(f"LLM QC Issues: {', '.join(llm_qc_result.issues)}")

                    # Run Gemini audio quality control if enabled
                    audio_qc_result = None
                    if self.audio_qc_enabled:
                        logger.info("Running Gemini audio quality control")
                        audio_qc_result = self.gemini_audio_qc.analyze_audio(
                            audio_data=audio_data,
                            original_script=item.script_text,
                            context={
                                'target_duration': item.target_duration,
                                'notes': item.notes
                            }
                        )

                        # Log Audio QC results
                        logger.info(
                            f"Audio QC: {audio_qc_result.status.upper()} "
                            f"(score: {audio_qc_result.score}/100)"
                        )
                        if audio_qc_result.strengths:
                            logger.info(f"Audio QC Strengths: {', '.join(audio_qc_result.strengths)}")
                        if audio_qc_result.issues:
                            logger.info(f"Audio QC Issues: {', '.join(audio_qc_result.issues)}")

                    # Check if Audio QC failed and we should retry with suggested tags
                    should_retry_for_audio_qc = False
                    if audio_qc_result and audio_qc_result.status == 'fail':
                        if attempt < max_retries and audio_qc_result.suggested_audio_tags:
                            # Audio QC failed with suggestions - retry with those tags
                            qc_suggested_tags = audio_qc_result.suggested_audio_tags
                            logger.info(
                                f"Audio QC failed with suggestions: {qc_suggested_tags}. "
                                f"Retrying with audio tags (attempt {attempt + 1}/{max_retries})"
                            )
                            should_retry_for_audio_qc = True

                    if should_retry_for_audio_qc:
                        # Continue loop to retry with QC-suggested tags
                        continue

                    # Determine final status based on all checks
                    if quality_report.passed and verification_result.passed:
                        # Check LLM QC if available
                        if llm_qc_result:
                            if llm_qc_result.status == 'fail':
                                status = 'needs_review'
                                issues.append(f"LLM QC failed: {llm_qc_result.reasoning}")
                            elif llm_qc_result.status == 'flag':
                                status = 'needs_review'
                                issues.append(f"LLM QC flagged for review: {llm_qc_result.reasoning}")
                            else:
                                status = 'completed'
                        else:
                            status = 'completed'

                        # Also check Audio QC if available
                        if audio_qc_result:
                            if audio_qc_result.status == 'fail':
                                status = 'needs_review'
                                issues.append(f"Audio QC failed: {audio_qc_result.reasoning}")
                            elif audio_qc_result.status == 'flag':
                                status = 'needs_review'
                                issues.append(f"Audio QC flagged for review: {audio_qc_result.reasoning}")
                    else:
                        status = 'needs_review'
                        if quality_report.issues:
                            issues.extend(quality_report.issues)
                        if verification_result.details:
                            issues.append(verification_result.details)

                    # Save audio
                    audio_path = self.output_manager.save_audio(
                        audio_data,
                        item.output_filename,
                        status=status
                    )

                    # Create result
                    return GenerationResult(
                        filename=item.output_filename,
                        status=status,
                        attempts=attempt,
                        final_duration=actual_duration,
                        target_duration=item.target_duration,
                        duration_diff=actual_duration - item.target_duration,
                        quality_passed=quality_report.passed,
                        verification_accuracy=verification_result.accuracy,
                        issues=issues,
                        notes=item.notes or "",
                        audio_path=audio_path,
                        llm_qc_status=llm_qc_result.status if llm_qc_result else None,
                        llm_qc_score=llm_qc_result.score if llm_qc_result else None,
                        llm_qc_issues=llm_qc_result.issues if llm_qc_result else [],
                        llm_qc_guidance=llm_qc_result.guidance if llm_qc_result else None,
                        audio_qc_status=audio_qc_result.status if audio_qc_result else None,
                        audio_qc_score=audio_qc_result.score if audio_qc_result else None,
                        audio_qc_issues=audio_qc_result.issues if audio_qc_result else [],
                        audio_qc_strengths=audio_qc_result.strengths if audio_qc_result else [],
                        audio_qc_guidance=audio_qc_result.guidance if audio_qc_result else None,
                        audio_qc_suggested_tags=qc_suggested_tags
                    )

                else:
                    # Timing not acceptable, calculate adjustment
                    logger.warning(
                        f"Timing outside tolerance: "
                        f"{actual_duration:.2f}s vs {item.target_duration:.2f}s"
                    )

                    if attempt < max_retries:
                        # Calculate new speed
                        adjustment = self.timing_adjuster.calculate_adjustment(
                            current_duration=actual_duration,
                            target_duration=item.target_duration,
                            current_speed=current_speed
                        )

                        # Use adjusted speed (clamped to bounds if needed)
                        current_speed = adjustment.new_speed

                        if adjustment.is_achievable:
                            logger.info(
                                f"Calculated achievable speed adjustment: new_speed={current_speed:.2f}"
                            )
                        else:
                            # Speed is outside bounds but try with clamped value anyway
                            logger.warning(
                                f"{adjustment.reason}"
                            )
                            logger.info(
                                f"Retrying with clamped speed: {current_speed:.2f}"
                            )
                            # Track the issue but continue trying
                            if adjustment.reason not in issues:
                                issues.append(adjustment.reason)
                    else:
                        # Max retries reached - use best attempt
                        logger.warning(f"Max retries reached for {item.output_filename}")

                        if best_attempt:
                            logger.info(
                                f"Saving best attempt (#{best_attempt['attempt_number']}): "
                                f"{best_attempt['actual_duration']:.2f}s "
                                f"(off by {best_duration_diff:.2f}s)"
                            )

                            # Run quality checks on best attempt
                            quality_report = self.quality_checker.run_all_checks(
                                best_attempt['audio_data'],
                                metadata={'target_duration': item.target_duration}
                            )

                            # Run speech verification on best attempt
                            verification_result = self.speech_verifier.verify_content(
                                original_text=item.script_text,
                                audio_data=best_attempt['audio_data']
                            )

                            # Run LLM QC if enabled
                            llm_qc_result = None
                            if self.llm_qc_enabled and verification_result.transcribed_text:
                                logger.info("Running LLM quality control on best attempt")
                                llm_qc_result = self.llm_quality_checker.analyze_transcription(
                                    original_script=item.script_text,
                                    transcription=verification_result.transcribed_text,
                                    context={
                                        'target_duration': item.target_duration,
                                        'notes': item.notes
                                    }
                                )
                                logger.info(
                                    f"LLM QC: {llm_qc_result.status.upper()} "
                                    f"(score: {llm_qc_result.score}/100)"
                                )

                            # Run Gemini audio QC if enabled
                            audio_qc_result = None
                            if self.audio_qc_enabled:
                                logger.info("Running Gemini audio quality control on best attempt")
                                audio_qc_result = self.gemini_audio_qc.analyze_audio(
                                    audio_data=best_attempt['audio_data'],
                                    original_script=item.script_text,
                                    context={
                                        'target_duration': item.target_duration,
                                        'notes': item.notes
                                    }
                                )
                                logger.info(
                                    f"Audio QC: {audio_qc_result.status.upper()} "
                                    f"(score: {audio_qc_result.score}/100)"
                                )

                            # Build issues list
                            attempt_issues = [f"Max retries exceeded, timing not achieved (best: {best_duration_diff:.2f}s off)"]
                            if quality_report.issues:
                                attempt_issues.extend(quality_report.issues)
                            if verification_result.details:
                                attempt_issues.append(verification_result.details)

                            # Save best attempt with needs_review status
                            audio_path = self.output_manager.save_audio(
                                best_attempt['audio_data'],
                                item.output_filename,
                                status='needs_review'
                            )

                            return GenerationResult(
                                filename=item.output_filename,
                                status='needs_review',
                                attempts=attempt,
                                final_duration=best_attempt['actual_duration'],
                                target_duration=item.target_duration,
                                duration_diff=best_attempt['actual_duration'] - item.target_duration,
                                quality_passed=quality_report.passed,
                                verification_accuracy=verification_result.accuracy,
                                issues=attempt_issues,
                                notes=item.notes or "",
                                audio_path=audio_path,
                                llm_qc_status=llm_qc_result.status if llm_qc_result else None,
                                llm_qc_score=llm_qc_result.score if llm_qc_result else None,
                                llm_qc_issues=llm_qc_result.issues if llm_qc_result else [],
                                llm_qc_guidance=llm_qc_result.guidance if llm_qc_result else None,
                                audio_qc_status=audio_qc_result.status if audio_qc_result else None,
                                audio_qc_score=audio_qc_result.score if audio_qc_result else None,
                                audio_qc_issues=audio_qc_result.issues if audio_qc_result else [],
                                audio_qc_strengths=audio_qc_result.strengths if audio_qc_result else [],
                                audio_qc_guidance=audio_qc_result.guidance if audio_qc_result else None,
                                audio_qc_suggested_tags=qc_suggested_tags
                            )
                        else:
                            # No successful attempts at all
                            return GenerationResult(
                                filename=item.output_filename,
                                status='failed',
                                attempts=attempt,
                                target_duration=item.target_duration,
                                error="No successful audio generation in any attempt"
                            )

            except Exception as e:
                logger.error(f"Attempt {attempt} failed: {e}")

                if attempt >= max_retries:
                    # Failed after all retries
                    return GenerationResult(
                        filename=item.output_filename,
                        status='failed',
                        attempts=attempt,
                        target_duration=item.target_duration,
                        error=str(e)
                    )

        # This should not be reached, but included for safety
        return GenerationResult(
            filename=item.output_filename,
            status='failed',
            attempts=attempt,
            target_duration=item.target_duration,
            error="Unknown error occurred"
        )

    def validate_input(self, input_file: str) -> dict:
        """
        Validate input file without processing.

        Args:
            input_file: Path to input file

        Returns:
            Dictionary with validation results and summary
        """
        logger.info(f"Validating input file: {input_file}")

        is_valid, errors, summary = self.input_parser.validate_file(input_file)

        result = {
            'is_valid': is_valid,
            'errors': errors,
            'summary': summary
        }

        if is_valid:
            logger.info(f"Input file is valid: {summary}")
        else:
            logger.error(f"Input file validation failed: {errors}")

        return result

    def get_available_voices(self) -> list:
        """
        Get list of available voices from ElevenLabs account.

        Returns:
            List of voice dictionaries
        """
        return self.api_client.get_available_voices()
