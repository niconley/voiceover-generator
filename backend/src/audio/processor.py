"""
Audio processor module for handling audio file operations,
duration measurement, and audio format conversions.
"""
from io import BytesIO
from pathlib import Path
from typing import Union, Optional
import logging

from pydub import AudioSegment
from pydub.effects import normalize
from pydub.silence import detect_leading_silence

logger = logging.getLogger(__name__)


class AudioProcessor:
    """
    Handles audio file operations including:
    - Duration measurement
    - File saving and loading
    - Format conversion
    - Audio normalization
    """

    def __init__(
        self,
        default_format: str = "mp3",
        default_bitrate: str = "192k"
    ):
        """
        Initialize audio processor.

        Args:
            default_format: Default audio format for saving
            default_bitrate: Default bitrate for encoding
        """
        self.default_format = default_format
        self.default_bitrate = default_bitrate

        logger.info(
            f"AudioProcessor initialized: format={default_format}, "
            f"bitrate={default_bitrate}"
        )

    def get_duration(self, audio_data: Union[bytes, str, Path]) -> float:
        """
        Get audio duration in seconds.

        Args:
            audio_data: Audio data as bytes, file path string, or Path object

        Returns:
            Duration in seconds with millisecond precision

        Raises:
            ValueError: If audio data is invalid or cannot be loaded
        """
        try:
            if isinstance(audio_data, bytes):
                # Load from bytes
                audio = AudioSegment.from_file(BytesIO(audio_data))
            else:
                # Load from file path
                audio = AudioSegment.from_file(str(audio_data))

            duration = audio.duration_seconds

            logger.debug(f"Audio duration: {duration:.3f}s")
            return duration

        except Exception as e:
            logger.error(f"Failed to get audio duration: {e}")
            raise ValueError(f"Invalid audio data: {e}")

    def trim_silence(
        self,
        audio_data: bytes,
        silence_threshold: int = -50,
        chunk_size: int = 10,
        padding_ms: int = 75
    ) -> bytes:
        """
        Remove silence from the beginning and end of audio with padding.

        Args:
            audio_data: Input audio as bytes
            silence_threshold: Silence threshold in dBFS (default: -50 dB)
            chunk_size: Minimum silence length to detect in ms (default: 10ms)
            padding_ms: Padding to leave at start/end in ms (default: 75ms)

        Returns:
            Trimmed audio as bytes with padding

        Raises:
            ValueError: If audio data is invalid
        """
        try:
            # Load audio
            audio = AudioSegment.from_file(BytesIO(audio_data))
            original_duration = audio.duration_seconds

            # Detect leading and trailing silence
            start_trim = detect_leading_silence(audio, silence_threshold, chunk_size)
            end_trim = detect_leading_silence(audio.reverse(), silence_threshold, chunk_size)

            # Apply padding to avoid abrupt cutoffs
            # Subtract padding from trim points (but don't go negative)
            start_trim = max(0, start_trim - padding_ms)
            end_trim = max(0, end_trim - padding_ms)

            # Calculate actual content duration with padding
            duration = len(audio)
            trimmed = audio[start_trim:duration - end_trim]

            # Export to bytes
            output = BytesIO()
            trimmed.export(
                output,
                format=self.default_format,
                bitrate=self.default_bitrate
            )

            output_bytes = output.getvalue()
            trimmed_duration = trimmed.duration_seconds

            logger.info(
                f"Silence trimmed: {original_duration:.2f}s → {trimmed_duration:.2f}s "
                f"(removed {original_duration - trimmed_duration:.2f}s, "
                f"{((original_duration - trimmed_duration) / original_duration * 100):.1f}%, "
                f"padding: {padding_ms}ms)"
            )

            return output_bytes

        except Exception as e:
            logger.error(f"Failed to trim silence: {e}")
            raise ValueError(f"Cannot trim silence from audio: {e}")

    def save_audio(
        self,
        audio_data: bytes,
        output_path: Union[str, Path],
        format: Optional[str] = None,
        bitrate: Optional[str] = None,
        normalize_audio: bool = False
    ) -> Path:
        """
        Save audio data to a file.

        Args:
            audio_data: Audio data as bytes
            output_path: Output file path
            format: Audio format (mp3, wav, etc). If None, uses default
            bitrate: Bitrate for encoding. If None, uses default
            normalize_audio: Whether to normalize audio levels

        Returns:
            Path to saved file

        Raises:
            IOError: If file cannot be saved
        """
        output_path = Path(output_path)
        format = format or self.default_format
        bitrate = bitrate or self.default_bitrate

        try:
            # Load audio from bytes
            audio = AudioSegment.from_file(BytesIO(audio_data))

            # Normalize if requested
            if normalize_audio:
                logger.debug("Normalizing audio")
                audio = normalize(audio)

            # Ensure output directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Export to file
            audio.export(
                str(output_path),
                format=format,
                bitrate=bitrate
            )

            logger.info(
                f"Audio saved: {output_path} "
                f"(format={format}, bitrate={bitrate})"
            )

            return output_path

        except Exception as e:
            logger.error(f"Failed to save audio to {output_path}: {e}")
            raise IOError(f"Cannot save audio file: {e}")

    def load_audio(self, file_path: Union[str, Path]) -> bytes:
        """
        Load audio file as bytes.

        Args:
            file_path: Path to audio file

        Returns:
            Audio data as bytes

        Raises:
            FileNotFoundError: If file doesn't exist
            IOError: If file cannot be loaded
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Audio file not found: {file_path}")

        try:
            with open(file_path, 'rb') as f:
                audio_data = f.read()

            logger.debug(f"Loaded audio file: {file_path} ({len(audio_data)} bytes)")
            return audio_data

        except Exception as e:
            logger.error(f"Failed to load audio from {file_path}: {e}")
            raise IOError(f"Cannot load audio file: {e}")

    def change_speed(
        self,
        audio_data: bytes,
        speed_factor: float
    ) -> bytes:
        """
        Change the playback speed of audio.

        Args:
            audio_data: Input audio as bytes
            speed_factor: Speed multiplier (e.g., 0.7 = slower, 1.2 = faster)

        Returns:
            Speed-adjusted audio as bytes

        Raises:
            ValueError: If speed_factor is invalid
        """
        if speed_factor <= 0:
            raise ValueError("Speed factor must be positive")

        if speed_factor == 1.0:
            logger.debug("Speed factor is 1.0, returning original audio")
            return audio_data

        try:
            # Load audio
            audio = AudioSegment.from_file(BytesIO(audio_data))

            # Method 1: Change frame rate (pitch-preserving speed change)
            # This changes the playback speed by manipulating frame rate
            original_frame_rate = audio.frame_rate
            new_frame_rate = int(original_frame_rate * speed_factor)

            # Change frame rate
            audio_modified = audio._spawn(audio.raw_data, overrides={
                "frame_rate": new_frame_rate
            })

            # Convert back to original frame rate to maintain compatibility
            audio_modified = audio_modified.set_frame_rate(original_frame_rate)

            # Export to bytes
            output = BytesIO()
            audio_modified.export(
                output,
                format=self.default_format,
                bitrate=self.default_bitrate
            )

            output_bytes = output.getvalue()

            logger.info(
                f"Speed changed: factor={speed_factor:.2f}, "
                f"original_duration={audio.duration_seconds:.2f}s, "
                f"new_duration={audio_modified.duration_seconds:.2f}s"
            )

            return output_bytes

        except Exception as e:
            logger.error(f"Failed to change audio speed: {e}")
            raise ValueError(f"Cannot change audio speed: {e}")

    def convert_format(
        self,
        audio_data: bytes,
        target_format: str,
        bitrate: Optional[str] = None
    ) -> bytes:
        """
        Convert audio to different format.

        Args:
            audio_data: Original audio data
            target_format: Target format (mp3, wav, m4a, ogg, etc)
            bitrate: Bitrate for encoding (for lossy formats)

        Returns:
            Converted audio data as bytes

        Raises:
            ValueError: If conversion fails
        """
        bitrate = bitrate or self.default_bitrate

        try:
            # Load audio
            audio = AudioSegment.from_file(BytesIO(audio_data))

            # Convert to target format
            output_buffer = BytesIO()
            audio.export(
                output_buffer,
                format=target_format,
                bitrate=bitrate if target_format in ['mp3', 'm4a', 'ogg'] else None
            )

            converted_data = output_buffer.getvalue()

            logger.debug(
                f"Converted audio: {len(audio_data)} bytes -> "
                f"{len(converted_data)} bytes ({target_format})"
            )

            return converted_data

        except Exception as e:
            logger.error(f"Failed to convert audio to {target_format}: {e}")
            raise ValueError(f"Audio conversion failed: {e}")

    def get_audio_info(self, audio_data: Union[bytes, str, Path]) -> dict:
        """
        Get detailed audio information.

        Args:
            audio_data: Audio data as bytes or file path

        Returns:
            Dictionary with audio metadata:
                - duration_seconds: Duration in seconds
                - channels: Number of channels
                - sample_width: Sample width in bytes
                - frame_rate: Sample rate in Hz
                - frame_count: Total number of frames
        """
        try:
            if isinstance(audio_data, bytes):
                audio = AudioSegment.from_file(BytesIO(audio_data))
            else:
                audio = AudioSegment.from_file(str(audio_data))

            info = {
                "duration_seconds": audio.duration_seconds,
                "channels": audio.channels,
                "sample_width": audio.sample_width,
                "frame_rate": audio.frame_rate,
                "frame_count": audio.frame_count()
            }

            logger.debug(f"Audio info: {info}")
            return info

        except Exception as e:
            logger.error(f"Failed to get audio info: {e}")
            raise ValueError(f"Cannot get audio info: {e}")

    def normalize_audio_file(
        self,
        input_path: Union[str, Path],
        output_path: Optional[Union[str, Path]] = None
    ) -> Path:
        """
        Normalize audio levels in a file.

        Args:
            input_path: Input audio file path
            output_path: Output file path. If None, overwrites input

        Returns:
            Path to normalized file
        """
        input_path = Path(input_path)
        output_path = Path(output_path) if output_path else input_path

        try:
            # Load audio
            audio = AudioSegment.from_file(str(input_path))

            # Normalize
            normalized = normalize(audio)

            # Save
            normalized.export(
                str(output_path),
                format=output_path.suffix[1:] or self.default_format
            )

            logger.info(f"Normalized audio: {input_path} -> {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Failed to normalize audio: {e}")
            raise IOError(f"Audio normalization failed: {e}")
