"""
LLM-powered quality checker for voiceover transcriptions.
Uses Claude API to analyze transcriptions for quality issues.
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
    Uses Claude API to analyze voiceover transcriptions for quality issues.
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
            # Return a default "pass" on error to avoid blocking generation
            return QCResult(
                status='pass',
                score=75.0,
                issues=[f"QC analysis error: {str(e)}"],
                reasoning="Error during analysis - defaulting to pass"
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

        prompt = f"""You are a professional voiceover quality control analyst. Analyze this voiceover transcription and check for quality issues.

**Original Script:**
{original_script}

**Transcription (from Whisper):**
{transcription}
{context_str}

**Quality Checks to Perform:**

1. **Accuracy**: Are all words and numbers correct? Compare transcription to original.

2. **Phone Numbers**: Check if phone numbers sound natural with appropriate pauses.
   - ❌ BAD: "eighteen hundred two seven nine four three two" (run together)
   - ✅ GOOD: "eighteen hundred... two seven nine... four three two" (natural pauses)

3. **Number Pronunciation**: Are numbers pronounced clearly and correctly?
   - Check for: "fifty percent" vs "50%", "one eight hundred" vs "1-800"

4. **Punctuation Effects**: Are pauses, emphasis, and tone appropriate for punctuation?
   - Periods should have noticeable pauses
   - Exclamation marks should have energy
   - Commas should have slight pauses

5. **Audio Tags**: If audio tags were used (like [excited], [professional]), does the transcription suggest they were effective?

6. **Overall Clarity**: Is the speech clear, natural, and professional?

**Response Format:**
Respond ONLY with a valid JSON object in this exact format (no markdown, no extra text):

{{
  "status": "pass|flag|fail",
  "score": 0-100,
  "issues": ["list of specific issues found, or empty array if none"],
  "guidance": "specific regeneration guidance if status is fail, or null if pass/flag",
  "reasoning": "brief explanation of the analysis"
}}

**Status Definitions:**
- **pass**: No significant issues, voiceover is ready to use (score >= 85)
- **flag**: Minor issues, recommend manual review (score 60-84)
- **fail**: Critical issues, must regenerate (score < 60)

**Guidance Examples (only if status is "fail"):**
- "Add longer pauses between phone number segments. Say 'one eight hundred... pause... two seven nine... pause... four three two'"
- "Emphasize the word 'free' to highlight the offer"
- "Slow down when reading the phone number for clarity"

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
