"""
Voice browser utility for exploring and managing ElevenLabs voices.
"""
from pathlib import Path
from typing import List, Dict, Optional
import logging

import yaml
import pandas as pd

logger = logging.getLogger(__name__)


class VoiceBrowser:
    """
    Browse, search, and manage ElevenLabs voices.
    """

    def __init__(self, api_client):
        """
        Initialize voice browser.

        Args:
            api_client: ElevenLabsClient instance
        """
        self.api_client = api_client
        logger.info("VoiceBrowser initialized")

    def list_voices(
        self,
        filter_by: Optional[str] = None,
        category: Optional[str] = None
    ) -> pd.DataFrame:
        """
        List all available voices as a DataFrame.

        Args:
            filter_by: Filter voices by name (case-insensitive substring match)
            category: Filter by category

        Returns:
            DataFrame with voice information
        """
        voices = self.api_client.get_available_voices()

        # Convert to DataFrame
        df = pd.DataFrame(voices)

        # Apply filters
        if filter_by:
            df = df[df['name'].str.contains(filter_by, case=False, na=False)]

        if category:
            df = df[df['category'] == category]

        logger.info(f"Listed {len(df)} voices")
        return df

    def search_voices(
        self,
        query: str,
        search_fields: List[str] = None
    ) -> List[Dict]:
        """
        Search voices by query string.

        Args:
            query: Search query
            search_fields: Fields to search in (name, description, labels)

        Returns:
            List of matching voices
        """
        search_fields = search_fields or ['name', 'description']
        voices = self.api_client.get_available_voices()

        query_lower = query.lower()
        matches = []

        for voice in voices:
            for field in search_fields:
                value = voice.get(field, '')
                if isinstance(value, str) and query_lower in value.lower():
                    matches.append(voice)
                    break

        logger.info(f"Search for '{query}' found {len(matches)} matches")
        return matches

    def recommend_voice(
        self,
        use_case: str,
        gender: Optional[str] = None,
        accent: Optional[str] = None
    ) -> List[Dict]:
        """
        Recommend voices based on use case and criteria.

        Args:
            use_case: Use case (commercial, narration, casual, etc.)
            gender: Preferred gender
            accent: Preferred accent

        Returns:
            List of recommended voices
        """
        voices = self.api_client.get_available_voices()

        recommendations = []

        # Simple recommendation based on labels and description
        for voice in voices:
            labels = voice.get('labels', {})
            description = voice.get('description', '').lower()

            # Match use case
            if use_case.lower() in description:
                score = 2
            else:
                score = 1

            # Match gender
            if gender:
                gender_match = labels.get('gender', '').lower()
                if gender.lower() == gender_match:
                    score += 1

            # Match accent
            if accent:
                accent_match = labels.get('accent', '').lower()
                if accent.lower() in accent_match:
                    score += 1

            if score > 1:  # At least some match
                recommendations.append({
                    **voice,
                    'recommendation_score': score
                })

        # Sort by score
        recommendations.sort(key=lambda x: x['recommendation_score'], reverse=True)

        logger.info(
            f"Recommended {len(recommendations)} voices for "
            f"use_case='{use_case}', gender={gender}, accent={accent}"
        )

        return recommendations

    def preview_voice(
        self,
        voice_id: str,
        sample_text: str = "This is a preview of the voice.",
        output_path: Optional[Path] = None
    ) -> bytes:
        """
        Generate and optionally save a voice preview.

        Args:
            voice_id: Voice ID to preview
            sample_text: Text to use for preview
            output_path: Optional path to save preview audio

        Returns:
            Audio preview as bytes
        """
        logger.info(f"Generating preview for voice: {voice_id}")

        audio_data = self.api_client.generate_preview(
            voice_id=voice_id,
            sample_text=sample_text
        )

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with open(output_path, 'wb') as f:
                f.write(audio_data)

            logger.info(f"Saved preview to: {output_path}")

        return audio_data

    def save_voice_catalog(
        self,
        output_path: Path,
        format: str = 'yaml'
    ):
        """
        Save voice catalog to file.

        Args:
            output_path: Path to save catalog
            format: Output format (yaml, json, csv)
        """
        voices = self.api_client.get_available_voices()
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if format == 'yaml':
            voice_data = {
                'voices': {
                    voice['name'].lower().replace(' ', '_'): {
                        'id': voice['id'],
                        'name': voice['name'],
                        'description': voice.get('description', ''),
                        'category': voice.get('category', ''),
                        'labels': voice.get('labels', {})
                    }
                    for voice in voices
                }
            }

            with open(output_path, 'w') as f:
                yaml.dump(voice_data, f, default_flow_style=False, sort_keys=False)

        elif format == 'json':
            import json
            with open(output_path, 'w') as f:
                json.dump(voices, f, indent=2)

        elif format == 'csv':
            df = pd.DataFrame(voices)
            df.to_csv(output_path, index=False)

        else:
            raise ValueError(f"Unsupported format: {format}")

        logger.info(f"Saved voice catalog to: {output_path}")

    def compare_voices(
        self,
        voice_ids: List[str],
        sample_text: str = "This is a comparison sample."
    ) -> Dict[str, bytes]:
        """
        Generate previews for multiple voices for comparison.

        Args:
            voice_ids: List of voice IDs to compare
            sample_text: Text to use for all previews

        Returns:
            Dictionary mapping voice IDs to audio data
        """
        previews = {}

        for voice_id in voice_ids:
            try:
                audio_data = self.preview_voice(voice_id, sample_text)
                previews[voice_id] = audio_data
            except Exception as e:
                logger.error(f"Failed to generate preview for {voice_id}: {e}")

        logger.info(f"Generated {len(previews)} voice previews")
        return previews

    def get_voice_details(self, voice_identifier: str) -> Optional[Dict]:
        """
        Get detailed information about a voice by ID or name.

        Args:
            voice_identifier: Voice ID or name

        Returns:
            Voice information dictionary, or None if not found
        """
        # Try as ID first
        voice_info = self.api_client.get_voice_info(voice_identifier)

        if not voice_info:
            # Try as name
            voice_id = self.api_client.get_voice_by_name(voice_identifier)
            if voice_id:
                voice_info = self.api_client.get_voice_info(voice_id)

        return voice_info

    def create_voice_preset(
        self,
        name: str,
        voice_id: str,
        stability: float = 0.5,
        similarity_boost: float = 0.75,
        style: float = 0.0,
        description: str = "",
        tags: List[str] = None
    ) -> Dict:
        """
        Create a voice preset configuration.

        Args:
            name: Preset name
            voice_id: Voice ID
            stability: Stability setting
            similarity_boost: Similarity boost setting
            style: Style setting
            description: Preset description
            tags: Tags for categorization

        Returns:
            Preset configuration dictionary
        """
        preset = {
            'name': name,
            'voice_id': voice_id,
            'settings': {
                'stability': stability,
                'similarity_boost': similarity_boost,
                'style': style
            },
            'description': description,
            'tags': tags or []
        }

        logger.info(f"Created voice preset: {name}")
        return preset

    def save_presets(
        self,
        presets: List[Dict],
        output_path: Path
    ):
        """
        Save voice presets to YAML file.

        Args:
            presets: List of preset dictionaries
            output_path: Path to save presets
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        preset_data = {
            'presets': {
                preset['name']: {
                    'voice_id': preset['voice_id'],
                    'settings': preset['settings'],
                    'description': preset.get('description', ''),
                    'tags': preset.get('tags', [])
                }
                for preset in presets
            }
        }

        with open(output_path, 'w') as f:
            yaml.dump(preset_data, f, default_flow_style=False, sort_keys=False)

        logger.info(f"Saved {len(presets)} presets to: {output_path}")

    def load_presets(self, preset_path: Path) -> Dict:
        """
        Load voice presets from YAML file.

        Args:
            preset_path: Path to presets file

        Returns:
            Dictionary of presets
        """
        with open(preset_path, 'r') as f:
            data = yaml.safe_load(f)

        presets = data.get('presets', {})
        logger.info(f"Loaded {len(presets)} presets from: {preset_path}")

        return presets
