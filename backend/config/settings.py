"""
Configuration settings for the Voiceover Generator application.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = BASE_DIR / "output"
LOGS_DIR = BASE_DIR / "logs"
TEMPLATES_DIR = BASE_DIR / "input_templates"

# Ensure directories exist
OUTPUT_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR.mkdir(exist_ok=True)
(OUTPUT_DIR / "completed").mkdir(exist_ok=True)
(OUTPUT_DIR / "failed").mkdir(exist_ok=True)
(OUTPUT_DIR / "needs_review").mkdir(exist_ok=True)


class Config:
    """Main configuration class for the application."""

    # ==================== API Settings ====================
    ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
    ELEVENLABS_DEFAULT_MODEL = "eleven_v3"  # V3: Most expressive model with audio tags

    # Alternative models
    ELEVENLABS_TURBO_MODEL = "eleven_turbo_v2_5"  # Faster, less expressive
    ELEVENLABS_MULTILINGUAL_MODEL = "eleven_multilingual_v2"  # 30+ languages

    # Claude API for LLM-powered quality control
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    CLAUDE_MODEL = "claude-sonnet-4-5-20250929"  # Claude Sonnet 4.5 (latest)
    ENABLE_LLM_QC = os.getenv("ENABLE_LLM_QC", "true").lower() == "true"

    # ==================== Audio Settings ====================
    AUDIO_FORMAT = "mp3"
    SAMPLE_RATE = 44100
    BITRATE = "192k"

    # Silence trimming (applied before duration measurement)
    TRIM_SILENCE = True  # Automatically trim silence from start/end
    SILENCE_THRESHOLD = -50  # dBFS threshold for silence detection (-40 to -50 typical)
    SILENCE_CHUNK_SIZE = 10  # Minimum silence length in ms
    SILENCE_PADDING_MS = 75  # Padding to leave at edges (0.075s) to avoid abrupt cuts

    # Default voice settings
    DEFAULT_STABILITY = 0.5
    DEFAULT_SIMILARITY_BOOST = 0.75
    DEFAULT_STYLE = 0.0
    DEFAULT_SPEED = 1.0
    OPTIMIZE_STREAMING_LATENCY = 0  # No optimization for batch processing

    # ==================== Timing Settings ====================
    DURATION_TOLERANCE = 0.3  # ±0.3 seconds
    SPEED_MIN = 0.7  # Minimum speed multiplier (ElevenLabs constraint)
    SPEED_MAX = 1.2  # Maximum speed multiplier (ElevenLabs constraint)

    # ==================== Quality Check Thresholds ====================
    # Clipping detection
    MAX_CLIPPING_PERCENTAGE = 0.5  # Maximum 0.5% clipped samples
    CLIPPING_THRESHOLD = 0.99  # Amplitude threshold for clipping detection

    # Silence detection (for quality checks on trimmed audio)
    # Note: This checks for excessive silence WITHIN speech (not edges)
    MAX_SILENCE_RATIO = 0.25  # Maximum 25% silence (allows natural pauses)
    SILENCE_THRESHOLD_DB = -50.0  # Silence threshold in dB
    MIN_SILENCE_LEN = 500  # Minimum silence length in ms (ignore short pauses)

    # Speech verification
    MIN_VERIFICATION_ACCURACY = 95.0  # Minimum 95% word accuracy

    # Distortion detection
    DISTORTION_ZCR_THRESHOLD = 0.8  # Zero-crossing rate threshold

    # ==================== Retry Settings ====================
    MAX_RETRIES = 5  # Maximum retry attempts per voiceover (increased for better timing accuracy)
    RETRY_BASE_DELAY = 1.0  # Base delay in seconds
    RETRY_MAX_DELAY = 30.0  # Maximum delay in seconds

    # Retryable HTTP status codes
    RETRYABLE_STATUS_CODES = [429, 500, 503, 504]

    # ==================== Whisper Settings ====================
    WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
    # Available models: tiny, base, small, medium, large
    # base is recommended for balance of speed and accuracy

    # ==================== Output Settings ====================
    OUTPUT_DIR = OUTPUT_DIR
    OUTPUT_COMPLETED_DIR = OUTPUT_DIR / "completed"
    OUTPUT_FAILED_DIR = OUTPUT_DIR / "failed"
    OUTPUT_NEEDS_REVIEW_DIR = OUTPUT_DIR / "needs_review"
    LOGS_DIR = LOGS_DIR

    # ==================== Logging Settings ====================
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
    LOG_FILE = LOGS_DIR / "generation.log"

    # ==================== Web Server Settings ====================
    FLASK_PORT = int(os.getenv("FLASK_PORT", 5000))
    FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0")
    FLASK_DEBUG = os.getenv("FLASK_DEBUG", "False").lower() == "true"

    # Session management
    SECRET_KEY = os.getenv("SECRET_KEY", os.urandom(24).hex())
    UPLOAD_FOLDER = BASE_DIR / "uploads"
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max file size

    # ==================== Batch Processing Settings ====================
    MAX_CONCURRENT_REQUESTS = 5  # Maximum concurrent API requests
    BATCH_CHECKPOINT_INTERVAL = 5  # Save checkpoint every N items

    # ==================== CSV Column Names ====================
    CSV_COLUMNS = {
        "required": ["script_text", "target_duration", "output_filename"],
        "optional": [
            "voice_id",
            "voice_name",
            "stability",
            "similarity_boost",
            "style",
            "speed",
            "notes"
        ]
    }

    @classmethod
    def validate(cls) -> tuple[bool, list[str]]:
        """
        Validate configuration settings.

        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []

        # Check API key
        if not cls.ELEVENLABS_API_KEY:
            errors.append("ELEVENLABS_API_KEY is not set in .env file")

        # Check directories
        if not OUTPUT_DIR.exists():
            errors.append(f"Output directory does not exist: {OUTPUT_DIR}")

        if not LOGS_DIR.exists():
            errors.append(f"Logs directory does not exist: {LOGS_DIR}")

        # Check thresholds
        if cls.DURATION_TOLERANCE <= 0:
            errors.append("DURATION_TOLERANCE must be positive")

        if not (0 < cls.SPEED_MIN < cls.SPEED_MAX < 2.0):
            errors.append("Invalid speed range (SPEED_MIN, SPEED_MAX)")

        if not (0 <= cls.MAX_CLIPPING_PERCENTAGE <= 100):
            errors.append("MAX_CLIPPING_PERCENTAGE must be between 0 and 100")

        if not (0 <= cls.MAX_SILENCE_RATIO <= 1.0):
            errors.append("MAX_SILENCE_RATIO must be between 0 and 1")

        if not (0 <= cls.MIN_VERIFICATION_ACCURACY <= 100):
            errors.append("MIN_VERIFICATION_ACCURACY must be between 0 and 100")

        if cls.MAX_RETRIES < 1:
            errors.append("MAX_RETRIES must be at least 1")

        return len(errors) == 0, errors

    @classmethod
    def get_summary(cls) -> str:
        """
        Get a human-readable summary of key configuration settings.

        Returns:
            String summary of configuration
        """
        return f"""
Configuration Summary:
=====================
Model: {cls.ELEVENLABS_DEFAULT_MODEL}
Duration Tolerance: ±{cls.DURATION_TOLERANCE}s
Speed Range: {cls.SPEED_MIN}x - {cls.SPEED_MAX}x
Max Retries: {cls.MAX_RETRIES}

Quality Thresholds:
  - Max Clipping: {cls.MAX_CLIPPING_PERCENTAGE}%
  - Max Silence: {cls.MAX_SILENCE_RATIO * 100}%
  - Min Accuracy: {cls.MIN_VERIFICATION_ACCURACY}%

Whisper Model: {cls.WHISPER_MODEL}
Output Directory: {OUTPUT_DIR}
Log Level: {cls.LOG_LEVEL}
        """.strip()


# Create a singleton instance
config = Config()
