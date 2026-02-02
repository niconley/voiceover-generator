"""
Gemini-powered audio quality checker that directly analyzes audio files.
Uses Google Gemini 2.0 Flash for native audio understanding.
"""
from dataclasses import dataclass
from typing import List, Optional
import logging
import tempfile
from pathlib import Path

import google.generativeai as genai

logger = logging.getLogger(__name__)


@dataclass
class AudioQCResult:
    """Audio quality control result from Gemini analysis."""
    status: str  # 'pass', 'flag', 'fail'
    score: float  # 0-100 audio quality score
    issues: List[str]
    strengths: List[str]
    guidance: Optional[str] = None
    reasoning: str = ""
    suggested_audio_tags: List[str] = None  # e.g., ['excited', 'faster']
    phone_number_ok: Optional[bool] = None  # True/False/None if no phone number

    def __post_init__(self):
        if self.suggested_audio_tags is None:
            self.suggested_audio_tags = []


class GeminiAudioQC:
    """
    Uses Gemini API to directly analyze audio quality.
    Checks tone, pacing, delivery, and audio artifacts.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash-exp"
    ):
        """
        Initialize Gemini audio quality checker.

        Args:
            api_key: Google API key
            model: Gemini model to use (default: gemini-2.0-flash-exp)
        """
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model)

        logger.info(f"GeminiAudioQC initialized with model: {model}")

    def analyze_audio(
        self,
        audio_data: bytes,
        original_script: str,
        context: Optional[dict] = None
    ) -> AudioQCResult:
        """
        Analyze audio quality using Gemini's native audio understanding.

        Args:
            audio_data: Audio file bytes (MP3)
            original_script: Original script text for context
            context: Additional context (target duration, notes, etc.)

        Returns:
            AudioQCResult with status and detailed feedback
        """
        try:
            # Save audio to temp file for Gemini upload
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
                tmp.write(audio_data)
                tmp_path = tmp.name

            logger.info("Uploading audio to Gemini for analysis")

            # Upload audio file to Gemini
            audio_file = genai.upload_file(tmp_path)

            # Build the analysis prompt
            prompt = self._build_prompt(original_script, context)

            # Call Gemini API with audio
            logger.info("Sending audio to Gemini for quality analysis")
            response = self.model.generate_content(
                [audio_file, prompt],
                generation_config={
                    "temperature": 0.3,  # Lower temperature for consistent analysis
                    "top_p": 0.8,
                    "top_k": 40,
                    "max_output_tokens": 1024,
                }
            )

            # Clean up temp file
            Path(tmp_path).unlink(missing_ok=True)

            # Parse response
            result_text = response.text
            logger.debug(f"Gemini Audio QC response: {result_text}")

            # Extract structured data from response
            qc_result = self._parse_response(result_text)

            logger.info(f"Audio QC Status: {qc_result.status}, Score: {qc_result.score}")
            return qc_result

        except Exception as e:
            logger.error(f"Gemini audio QC failed: {e}")
            # Return "flag" on error so item goes to needs_review, not silent pass
            return AudioQCResult(
                status='flag',
                score=0.0,
                issues=[f"Audio QC error: {str(e)}"],
                strengths=[],
                reasoning="Error during audio analysis - flagging for manual review"
            )

    def _build_prompt(
        self,
        original_script: str,
        context: Optional[dict] = None
    ) -> str:
        """Build analysis prompt for Gemini."""
        import re

        target_duration = context.get('target_duration') if context else None
        notes = context.get('notes', '') if context else ''

        # Check if script contains a phone number
        phone_pattern = r'(\d{3}[-.\s]?\d{3}[-.\s]?\d{4}|\d{1}[-.\s]?\d{3}[-.\s]?\d{3}[-.\s]?\d{4}|1[-.\s]?800[-.\s]?\d{3}[-.\s]?\d{4})'
        has_phone_number = bool(re.search(phone_pattern, original_script)) or \
                          'eight hundred' in original_script.lower() or \
                          '800' in original_script

        # Build phone number section if applicable
        phone_section = ""
        if has_phone_number:
            phone_section = """
🚨 **CRITICAL: PHONE NUMBER PACING** 🚨

This script contains a phone number. This is the MOST IMPORTANT check.

**Listen carefully for phone number delivery:**

✅ GOOD phone number pacing:
- Clear pause between number groups: "1-800... 555... 1234"
- Each digit clearly pronounced
- Listener could write down the number on first listen
- Natural rhythm, not rushed
- Slight emphasis on each group

❌ BAD phone number pacing (MUST FAIL):
- Numbers run together: "1800-555-1234" spoken as one blur
- Rushed delivery where digits blend
- No pauses between groups
- Listener would need to replay to catch the number
- Robotic monotone through the number

**If phone number pacing is bad, this MUST be marked as FAIL regardless of other qualities.**
"""

        prompt = f"""You are an expert audio quality analyst for AI-generated voiceovers. Analyze this audio file and provide a detailed quality assessment.

**Original Script:**
"{original_script}"

{"**Target Duration:** " + str(target_duration) + " seconds" if target_duration else ""}
{"**Context/Notes:** " + notes if notes else ""}
{phone_section}
**Analyze the following aspects{" (Phone number pacing is #1 priority)" if has_phone_number else ""}:**

{"1. **Phone Number Pacing** (CRITICAL - check this FIRST):" if has_phone_number else ""}
{"   - Are there clear pauses between number groups?" if has_phone_number else ""}
{"   - Could a listener write down the number on first listen?" if has_phone_number else ""}
{"   - Is each digit clearly pronounced?" if has_phone_number else ""}
{"" if has_phone_number else ""}
{"2" if has_phone_number else "1"}. **Delivery & Tone:**
   - Does the tone match the script content? (e.g., excited, warm, professional, urgent)
   - Is the emotional delivery appropriate and natural?
   - Does it sound genuine or robotic?

{"3" if has_phone_number else "2"}. **Pacing & Rhythm:**
   - Is the speaking pace appropriate (not too fast/slow)?
   - Are there natural pauses and breathing?
   - Does it flow smoothly?

{"4" if has_phone_number else "3"}. **Vocal Quality:**
   - Is pronunciation clear and accurate?
   - Are there any mispronunciations or glitches?
   - Is the voice quality consistent?

{"5" if has_phone_number else "4"}. **Audio Artifacts:**
   - Any robotic/synthetic sounds?
   - Unnatural transitions or cuts?
   - Audio glitches or distortions?

**Response Format:**
Provide your analysis in this exact format:

STATUS: [PASS/FLAG/FAIL]
SCORE: [0-100]
{"PHONE_NUMBER_OK: [YES/NO] (REQUIRED - did the phone number have proper pacing?)" if has_phone_number else ""}
STRENGTHS:
- [List 2-3 positive aspects]
ISSUES:
- [List any problems, or "None" if perfect]
REASONING: [Brief explanation of your assessment]
GUIDANCE: [If FAIL or FLAG, provide specific suggestions for improvement]
AUDIO_TAGS: [If FAIL, suggest ElevenLabs audio tags to fix the issues, or "none" if pass]

**Available Audio Tags for AUDIO_TAGS field:**
- Emotion: [excited], [happy], [sad], [angry], [calm], [serious]
- Style: [professional], [conversational], [narrative], [friendly], [authoritative]
- Pacing: [slower], [faster]
- Emphasis: [whisper]

Example AUDIO_TAGS responses:
- "excited, faster" (for dull delivery that needs energy)
- "professional, slower" (for rushed unprofessional delivery)
- "friendly, conversational" (for robotic/stiff delivery)
- "none" (if no tags needed)
{"" if not has_phone_number else "⚠️ REMEMBER: If phone number pacing is poor, STATUS must be FAIL and suggest 'slower' in AUDIO_TAGS."}
"""
        return prompt

    def _parse_response(self, response_text: str) -> AudioQCResult:
        """Parse Gemini response into structured AudioQCResult."""

        lines = response_text.strip().split('\n')

        status = 'pass'
        score = 75.0
        issues = []
        strengths = []
        reasoning = ""
        guidance = None
        audio_tags = []
        phone_number_ok = None  # None = no phone number in script

        current_section = None

        for line in lines:
            line = line.strip()

            if line.startswith('STATUS:'):
                status_text = line.replace('STATUS:', '').strip().lower()
                if 'fail' in status_text:
                    status = 'fail'
                elif 'flag' in status_text:
                    status = 'flag'
                else:
                    status = 'pass'

            elif line.startswith('SCORE:'):
                try:
                    score = float(line.replace('SCORE:', '').strip())
                except:
                    score = 75.0

            elif line.startswith('STRENGTHS:'):
                current_section = 'strengths'

            elif line.startswith('ISSUES:'):
                current_section = 'issues'

            elif line.startswith('REASONING:'):
                current_section = 'reasoning'
                reasoning = line.replace('REASONING:', '').strip()

            elif line.startswith('GUIDANCE:'):
                current_section = 'guidance'
                guidance = line.replace('GUIDANCE:', '').strip()

            elif line.startswith('AUDIO_TAGS:'):
                current_section = 'audio_tags'
                tags_text = line.replace('AUDIO_TAGS:', '').strip().lower()
                if tags_text and tags_text != 'none':
                    # Parse comma-separated tags, clean up brackets
                    audio_tags = [
                        tag.strip().strip('[]')
                        for tag in tags_text.split(',')
                        if tag.strip() and tag.strip().lower() != 'none'
                    ]

            elif line.startswith('PHONE_NUMBER_OK:'):
                phone_text = line.replace('PHONE_NUMBER_OK:', '').strip().lower()
                if 'yes' in phone_text:
                    phone_number_ok = True
                elif 'no' in phone_text:
                    phone_number_ok = False
                    # If phone number pacing is bad, ensure we flag/fail
                    if status == 'pass':
                        status = 'fail'
                    if 'slower' not in audio_tags:
                        audio_tags.append('slower')

            elif line.startswith('-') and current_section:
                item = line.lstrip('- ').strip()
                if item and item.lower() != 'none':
                    if current_section == 'strengths':
                        strengths.append(item)
                    elif current_section == 'issues':
                        issues.append(item)

            elif current_section == 'reasoning' and line:
                reasoning += ' ' + line

            elif current_section == 'guidance' and line:
                if guidance:
                    guidance += ' ' + line
                else:
                    guidance = line

        return AudioQCResult(
            status=status,
            score=score,
            issues=issues if issues else [],
            strengths=strengths if strengths else [],
            guidance=guidance,
            reasoning=reasoning.strip(),
            suggested_audio_tags=audio_tags,
            phone_number_ok=phone_number_ok
        )
