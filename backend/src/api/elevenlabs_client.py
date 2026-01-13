"""
ElevenLabs API client wrapper with speed control and retry logic.
"""
from typing import Optional, Dict, List
import logging

from elevenlabs import ElevenLabs, Voice, VoiceSettings

logger = logging.getLogger(__name__)


class ElevenLabsClient:
    """
    Wrapper for ElevenLabs API with enhanced functionality:
    - Speech generation with speed control
    - Voice management and selection
    - Error handling and validation
    """

    def __init__(
        self,
        api_key: str,
        default_model: str = "eleven_turbo_v2_5"
    ):
        """
        Initialize ElevenLabs client.

        Args:
            api_key: ElevenLabs API key
            default_model: Default model ID to use for generation

        Raises:
            ValueError: If API key is invalid or missing
        """
        if not api_key:
            raise ValueError("ElevenLabs API key is required")

        self.api_key = api_key
        self.default_model = default_model
        self.client = ElevenLabs(api_key=api_key)

        logger.info(f"ElevenLabs client initialized with model: {default_model}")

    def generate_speech(
        self,
        text: str,
        voice_id: str,
        model: Optional[str] = None,
        stability: float = 0.5,
        similarity_boost: float = 0.75,
        style: float = 0.0,
        speed: float = 1.0,
        use_speaker_boost: bool = True
    ) -> bytes:
        """
        Generate speech from text with specified parameters.

        V3 Audio Tags: Use inline tags in the text for emotion/delivery control.
        Examples: [happy], [whispers], [nervously], [excited], [sad], [laughs]

        Args:
            text: Text to convert to speech (can include [audio tags] for v3)
            voice_id: ElevenLabs voice ID
            model: Model ID (if None, uses default: eleven_v3)
            stability: Stability setting (0.0-1.0, default: 0.5)
            similarity_boost: Clarity + similarity boost (0.0-1.0, default: 0.75)
            style: Style exaggeration (0.0-1.0, default: 0.0)
            speed: Speed multiplier (0.5-2.0, optimal: 0.7-1.2)
            use_speaker_boost: Enable speaker boost for clarity

        Returns:
            Audio data as bytes (MP3 format)

        Raises:
            ValueError: If parameters are invalid
            Exception: If API call fails
        """
        # Validate parameters
        self._validate_parameters(
            text=text,
            voice_id=voice_id,
            stability=stability,
            similarity_boost=similarity_boost,
            style=style,
            speed=speed
        )

        model = model or self.default_model

        # V3 requires discrete stability values: 0.0, 0.5, or 1.0
        if model == "eleven_v3":
            # Round to nearest valid V3 stability value
            if stability < 0.25:
                stability = 0.0
            elif stability < 0.75:
                stability = 0.5
            else:
                stability = 1.0

        logger.info(
            f"Generating speech: voice={voice_id}, model={model}, "
            f"speed={speed:.2f}, stability={stability:.2f}"
        )

        try:
            # Create voice settings with speed parameter
            voice_settings = VoiceSettings(
                stability=stability,
                similarity_boost=similarity_boost,
                style=style,
                speed=speed,  # Speed is a VoiceSettings parameter
                use_speaker_boost=use_speaker_boost
            )

            # Generate audio
            # Note: V3 prompting uses inline audio tags like [happy], [whispers]
            # No separate prompt_text parameter needed
            request_params = {
                "text": text,
                "voice_id": voice_id,
                "model_id": model,
                "voice_settings": voice_settings,
                "output_format": "mp3_44100_192"  # 44.1kHz, 192kbps
            }

            audio_generator = self.client.text_to_speech.convert(**request_params)

            # Collect audio bytes from generator
            audio_bytes = b"".join(audio_generator)

            logger.info(
                f"Speech generated successfully: {len(audio_bytes)} bytes"
            )

            return audio_bytes

        except Exception as e:
            logger.error(f"Speech generation failed: {e}")
            raise

    def generate_speech_with_speed(
        self,
        text: str,
        voice_id: str,
        speed: float = 1.0,
        **kwargs
    ) -> bytes:
        """
        Generate speech with explicit speed control.

        This method wraps generate_speech but emphasizes the speed parameter
        for timing-critical generation.

        Args:
            text: Text to convert to speech
            voice_id: ElevenLabs voice ID
            speed: Speed multiplier (0.7-1.2)
            **kwargs: Additional arguments passed to generate_speech

        Returns:
            Audio data as bytes
        """
        # Note: ElevenLabs API supports speed control via the model_id parameter
        # For fine-grained speed control, we may need to use specific models
        # or apply post-processing. For now, we'll use the standard generation
        # and note that precise speed control may require additional handling.

        logger.debug(f"Generating speech with speed={speed:.2f}")

        return self.generate_speech(
            text=text,
            voice_id=voice_id,
            speed=speed,
            **kwargs
        )

    def get_available_voices(self) -> List[Dict]:
        """
        Retrieve all available voices from the account.

        Returns:
            List of voice dictionaries with id, name, and metadata
        """
        try:
            logger.info("Fetching available voices")

            voices = self.client.voices.get_all()

            voice_list = []
            for voice in voices.voices:
                voice_dict = {
                    "id": voice.voice_id,
                    "name": voice.name,
                    "category": voice.category if hasattr(voice, 'category') else None,
                    "description": voice.description if hasattr(voice, 'description') else None,
                    "labels": voice.labels if hasattr(voice, 'labels') else {}
                }
                voice_list.append(voice_dict)

            logger.info(f"Retrieved {len(voice_list)} voices")
            return voice_list

        except Exception as e:
            logger.error(f"Failed to fetch voices: {e}")
            raise

    def get_voice_by_name(self, name: str) -> Optional[str]:
        """
        Get voice ID by voice name.

        Args:
            name: Voice name to search for

        Returns:
            Voice ID if found, None otherwise
        """
        try:
            voices = self.get_available_voices()

            for voice in voices:
                if voice["name"].lower() == name.lower():
                    logger.info(f"Found voice '{name}': {voice['id']}")
                    return voice["id"]

            logger.warning(f"Voice '{name}' not found")
            return None

        except Exception as e:
            logger.error(f"Error searching for voice '{name}': {e}")
            return None

    def get_voice_info(self, voice_id: str) -> Optional[Dict]:
        """
        Get detailed information about a specific voice.

        Args:
            voice_id: Voice ID to query

        Returns:
            Voice information dictionary, or None if not found
        """
        try:
            logger.info(f"Fetching info for voice: {voice_id}")

            voice = self.client.voices.get(voice_id=voice_id)

            voice_info = {
                "id": voice.voice_id,
                "name": voice.name,
                "category": voice.category if hasattr(voice, 'category') else None,
                "description": voice.description if hasattr(voice, 'description') else None,
                "labels": voice.labels if hasattr(voice, 'labels') else {},
                "settings": {
                    "stability": voice.settings.stability if voice.settings else None,
                    "similarity_boost": voice.settings.similarity_boost if voice.settings else None,
                    "style": voice.settings.style if voice.settings else None,
                    "use_speaker_boost": voice.settings.use_speaker_boost if voice.settings else None
                } if voice.settings else None
            }

            logger.info(f"Retrieved info for voice '{voice.name}'")
            return voice_info

        except Exception as e:
            logger.error(f"Failed to get voice info for {voice_id}: {e}")
            return None

    def generate_preview(
        self,
        voice_id: str,
        sample_text: str = "This is a preview of the voice."
    ) -> bytes:
        """
        Generate a quick preview of a voice.

        Args:
            voice_id: Voice ID to preview
            sample_text: Sample text to use for preview

        Returns:
            Audio preview as bytes
        """
        logger.info(f"Generating preview for voice: {voice_id}")

        return self.generate_speech(
            text=sample_text,
            voice_id=voice_id,
            model=self.default_model
        )

    def _validate_parameters(
        self,
        text: str,
        voice_id: str,
        stability: float,
        similarity_boost: float,
        style: float,
        speed: float
    ):
        """
        Validate generation parameters.

        Args:
            text: Text to validate
            voice_id: Voice ID to validate
            stability: Stability value
            similarity_boost: Similarity boost value
            style: Style value
            speed: Speed value

        Raises:
            ValueError: If any parameter is invalid
        """
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")

        if not voice_id:
            raise ValueError("Voice ID is required")

        if not (0 <= stability <= 1):
            raise ValueError("Stability must be between 0 and 1")

        if not (0 <= similarity_boost <= 1):
            raise ValueError("Similarity boost must be between 0 and 1")

        if not (0 <= style <= 1):
            raise ValueError("Style must be between 0 and 1")

        if not (0.25 <= speed <= 2.0):
            # ElevenLabs supports speed range approximately 0.25 to 2.0
            # but optimal range is 0.7 to 1.2
            logger.warning(
                f"Speed {speed:.2f} is outside optimal range [0.7, 1.2]. "
                f"Results may vary."
            )

    def estimate_character_cost(self, text: str) -> int:
        """
        Estimate the character cost for generating speech from text.

        ElevenLabs charges based on character count.

        Args:
            text: Text to estimate cost for

        Returns:
            Number of characters that will be charged
        """
        return len(text)

    def get_subscription_info(self) -> Optional[Dict]:
        """
        Get current subscription and usage information.

        Returns:
            Dictionary with subscription details, or None if unavailable
        """
        try:
            logger.info("Fetching subscription info")

            subscription = self.client.user.get_subscription()

            info = {
                "tier": subscription.tier if hasattr(subscription, 'tier') else None,
                "character_count": subscription.character_count if hasattr(subscription, 'character_count') else None,
                "character_limit": subscription.character_limit if hasattr(subscription, 'character_limit') else None,
                "can_use_instant_voice_cloning": subscription.can_use_instant_voice_cloning if hasattr(subscription, 'can_use_instant_voice_cloning') else None,
            }

            logger.info(f"Subscription: {info.get('tier', 'unknown')}")
            return info

        except Exception as e:
            logger.error(f"Failed to get subscription info: {e}")
            return None
