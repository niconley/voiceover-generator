"""
LLM-powered transcription accuracy checker.
Uses Claude API to compare original script text against Whisper transcription.
NOTE: This checker only analyzes TEXT - it cannot hear the audio.
For tone/pacing/delivery checks, use GeminiAudioQC which listens to the actual audio.
"""
from dataclasses import dataclass
from typing import List, Optional
import logging
import json

from anthropic import Anthropic

logger = logging.getLogger(__name__)


@dataclass
class QCResult:
    """Quality control result from LLM analysis."""
    status: str  # 'pass', 'flag', 'fail'
    score: float  # 0-100 quality score
    issues: List[str]
    guidance: Optional[str] = None  # Specific guidance for regeneration
    reasoning: str = ""


class LLMQualityChecker:
    """
    Uses Claude API to compare original script against Whisper transcription.

    This checker analyzes TEXT ONLY - it cannot hear the audio.
    It checks for: missing words, wrong words, number/phone transcription errors.

    For audio quality checks (tone, pacing, delivery), use GeminiAudioQC instead.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-5-20250929"
    ):
        """
        Initialize LLM quality checker.

        Args:
            api_key: Anthropic API key
            model: Claude model to use (default: Claude Sonnet 4.5)
        """
        self.client = Anthropic(api_key=api_key)
        self.model = model

        logger.info(f"LLMQualityChecker initialized with model: {model}")

    def analyze_transcription(
        self,
        original_script: str,
        transcription: str,
        context: Optional[dict] = None
    ) -> QCResult:
        """
        Analyze transcription quality using Claude.

        Args:
            original_script: Original script text
            transcription: Whisper transcription
            context: Additional context (target duration, notes, etc.)

        Returns:
            QCResult with status and detailed feedback
        """
        try:
            # Build the analysis prompt
            prompt = self._build_prompt(original_script, transcription, context)

            # Call Claude API
            logger.info("Sending transcription to Claude for quality analysis")
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                temperature=0.3,  # Lower temperature for consistent analysis
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            # Parse response
            result_text = response.content[0].text
            logger.debug(f"Claude QC response: {result_text}")

            # Extract structured data from response
            qc_result = self._parse_response(result_text)

            logger.info(f"QC Status: {qc_result.status}, Score: {qc_result.score}")
            return qc_result

        except Exception as e:
            logger.error(f"LLM quality check failed: {e}")
            # Return "flag" on error so item goes to needs_review, not silent pass
            return QCResult(
                status='flag',
                score=0.0,
                issues=[f"QC analysis error: {str(e)}"],
                reasoning="Error during analysis - flagging for manual review"
            )

    def _build_prompt(
        self,
        original_script: str,
        transcription: str,
        context: Optional[dict]
    ) -> str:
        """Build the analysis prompt for Claude."""

        context_str = ""
        if context:
            if 'target_duration' in context:
                context_str += f"\nTarget Duration: {context['target_duration']}s"
            if 'notes' in context and context['notes']:
                context_str += f"\nNotes: {context['notes']}"

        prompt = f"""You are a voiceover transcription accuracy checker. Your job is to compare the original script to what Whisper transcribed from the generated audio.

IMPORTANT: You are analyzing TEXT only. You cannot hear the audio. Only check for issues that are visible in the transcription text.

**Original Script:**
{original_script}

**Transcription (from Whisper):**
{transcription}
{context_str}

**CRITICAL: Whisper Transcription Artifacts**

Whisper converts speech to text, so many "differences" are just transcription format changes, NOT actual errors. Do NOT flag these as issues:

✅ ACCEPTABLE variations (same meaning, different format):
- Numbers: "1-800" → "one eight hundred" or "eighteen hundred"
- Percentages: "50%" → "fifty percent" or "fifty per cent"
- Phone numbers: "1-800-279-4321" → "one eight hundred two seven nine four three two one"
- Currencies: "$100" → "one hundred dollars" or "a hundred dollars"
- Times: "9:30" → "nine thirty" or "half past nine"
- Ordinals: "1st" → "first", "2nd" → "second"
- Contractions: "don't" → "do not" (or vice versa)
- Minor filler words: slight "uh", "um" added by TTS
- Punctuation spoken: ellipsis as pause, etc.

❌ ACTUAL errors to flag:
- Wrong words entirely: "save" transcribed as "safe"
- Missing words: entire phrases not spoken
- Wrong numbers: "fifty" when script says "fifteen"
- Wrong names: "John" transcribed as "Jon" or completely different name
- Garbled/unintelligible: Whisper couldn't understand at all

**Checks to Perform:**

1. **Semantic Accuracy**: Is the MEANING preserved?
   - All key information present (names, numbers, offers, CTAs)
   - No wrong words that change meaning

2. **Number/Phone Verification**: Are digits CORRECT (not just formatted differently)?
   - "1-800-279-4321" → "one eight hundred two seven nine four three two one" = PASS
   - "1-800-279-4321" → "one eight hundred two seven nine four three two TWO" = FAIL (wrong digit)

3. **Critical Content**: Are brand names, product names, and key terms correct?

**DO NOT flag as errors:**
- Format differences (written vs spoken numbers)
- Minor transcription artifacts
- Whisper's interpretation of how numbers/symbols are spoken

**Response Format:**
Respond ONLY with valid JSON (no markdown):

{{
  "status": "pass|flag|fail",
  "score": 0-100,
  "issues": ["list of specific text differences found, or empty array if none"],
  "guidance": "what words/numbers need to be re-recorded if fail, otherwise null",
  "reasoning": "brief explanation of text comparison"
}}

**Status Definitions:**
- **pass** (score >= 85): Transcription matches script, minor acceptable variations only
- **flag** (score 60-84): Some differences that may need human review
- **fail** (score < 60): Significant words missing, wrong, or garbled

Analyze now:"""

        return prompt

    def _parse_response(self, response_text: str) -> QCResult:
        """Parse Claude's JSON response into QCResult."""
        try:
            # Try to extract JSON from response
            response_text = response_text.strip()

            # Remove markdown code blocks if present
            if response_text.startswith('```'):
                lines = response_text.split('\n')
                response_text = '\n'.join(lines[1:-1])

            # Parse JSON
            data = json.loads(response_text)

            return QCResult(
                status=data['status'],
                score=float(data['score']),
                issues=data.get('issues', []),
                guidance=data.get('guidance'),
                reasoning=data.get('reasoning', '')
            )

        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse LLM response: {e}")
            logger.error(f"Raw response: {response_text}")

            # Fallback parsing - look for keywords in text
            text_lower = response_text.lower()

            if 'fail' in text_lower or 'critical' in text_lower:
                status = 'fail'
                score = 50.0
            elif 'flag' in text_lower or 'review' in text_lower:
                status = 'flag'
                score = 70.0
            else:
                status = 'pass'
                score = 85.0

            return QCResult(
                status=status,
                score=score,
                issues=["Failed to parse structured response"],
                reasoning=response_text[:200]  # First 200 chars
            )
