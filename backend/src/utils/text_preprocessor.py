"""
Text preprocessor for voiceover scripts.
Handles number formatting to ensure proper pronunciation by TTS.
"""
import re
import logging

logger = logging.getLogger(__name__)


class TextPreprocessor:
    """
    Preprocesses script text to improve TTS pronunciation.

    Handles:
    - Phone numbers: formats with pauses between groups
    - Digit sequences: converts to digit-by-digit pronunciation
    - Preserves prices, percentages, and ordinals
    """

    # Digit word mappings
    DIGIT_WORDS = {
        '0': 'zero',
        '1': 'one',
        '2': 'two',
        '3': 'three',
        '4': 'four',
        '5': 'five',
        '6': 'six',
        '7': 'seven',
        '8': 'eight',
        '9': 'nine',
    }

    def __init__(
        self,
        phone_group_separator: str = ", ",
        digit_separator: str = ", ",
        spell_out_digits: bool = False
    ):
        """
        Initialize text preprocessor.

        Args:
            phone_group_separator: Separator between phone number groups (default: ", ")
            digit_separator: Separator between individual digits (default: ", ")
            spell_out_digits: If True, convert digits to words (e.g., "2" -> "two")
        """
        self.phone_group_separator = phone_group_separator
        self.digit_separator = digit_separator
        self.spell_out_digits = spell_out_digits

    def preprocess(self, text: str) -> str:
        """
        Preprocess text for better TTS pronunciation.

        Args:
            text: Original script text

        Returns:
            Preprocessed text with formatted numbers
        """
        original_text = text

        # Process phone numbers first (before general digit processing)
        text = self._process_phone_numbers(text)

        # Process standalone digit sequences (not part of prices, percentages, etc.)
        text = self._process_digit_sequences(text)

        if text != original_text:
            logger.info(f"Preprocessed text: '{original_text[:50]}...' -> '{text[:50]}...'")

        return text

    def _process_phone_numbers(self, text: str) -> str:
        """
        Format phone numbers for clear pronunciation.

        Handles formats like:
        - 1-800-555-1234
        - (800) 555-1234
        - 800.555.1234
        - 800 555 1234
        - 8005551234
        """
        # 1-800 or 1-888 style numbers
        text = re.sub(
            r'\b1[-.\s]?(800|888|877|866|855|844|833)[-.\s]?(\d{3})[-.\s]?(\d{4})\b',
            lambda m: self._format_phone_match(m, has_one=True),
            text
        )

        # Standard 10-digit: (800) 555-1234 or 800-555-1234 or 800.555.1234
        text = re.sub(
            r'\(?\b(\d{3})\)?[-.\s]?(\d{3})[-.\s]?(\d{4})\b',
            lambda m: self._format_phone_match(m, has_one=False),
            text
        )

        return text

    def _format_phone_match(self, match, has_one: bool = False) -> str:
        """Format a phone number with hyphenated digit words and commas between groups.

        Example: 1-800-334-5768 -> One-eight-hundred, three-three-four, five-seven-six-eight
        """
        if has_one:
            # 1-800 style
            prefix = match.group(1)  # 800, 888, etc.
            mid = match.group(2)
            last = match.group(3)

            # Format: One-eight-hundred, three-three-four, five-seven-six-eight
            prefix_spelled = self._spell_digits_hyphenated(prefix)
            mid_spelled = self._spell_digits_hyphenated(mid)
            last_spelled = self._spell_digits_hyphenated(last)

            return f"One-{prefix_spelled}{self.phone_group_separator}{mid_spelled}{self.phone_group_separator}{last_spelled}"
        else:
            # Standard 10-digit
            area = match.group(1)
            mid = match.group(2)
            last = match.group(3)

            area_spelled = self._spell_digits_hyphenated(area)
            mid_spelled = self._spell_digits_hyphenated(mid)
            last_spelled = self._spell_digits_hyphenated(last)

            # Capitalize first letter
            area_spelled = area_spelled[0].upper() + area_spelled[1:] if area_spelled else area_spelled

            return f"{area_spelled}{self.phone_group_separator}{mid_spelled}{self.phone_group_separator}{last_spelled}"

    def _spell_digits_hyphenated(self, digits: str) -> str:
        """Spell out digits as hyphenated words for phone numbers.

        Example: 800 -> eight-hundred (special case), 334 -> three-three-four
        """
        # Special case for x00 patterns (800, 900, etc.)
        if len(digits) == 3 and digits[1:] == '00':
            return f"{self.DIGIT_WORDS[digits[0]]}-hundred"

        # Regular hyphenated digits
        return '-'.join(self.DIGIT_WORDS[d] for d in digits)

    def _spell_digits(self, digits: str) -> str:
        """Spell out digits as space-separated words."""
        return ' '.join(self.DIGIT_WORDS[d] for d in digits)

    def _format_digit_group(self, digits: str) -> str:
        """Format a group of digits with separators."""
        if self.spell_out_digits:
            return self.digit_separator.join(self.DIGIT_WORDS[d] for d in digits)
        else:
            return self.digit_separator.join(digits)

    def _process_digit_sequences(self, text: str) -> str:
        """
        Process standalone digit sequences (not prices, percentages, etc.).

        Converts sequences like "248" to "2, 4, 8" for digit-by-digit pronunciation.
        """
        # Skip if it looks like a price ($XX.XX)
        # Skip if it looks like a percentage (XX%)
        # Skip if it looks like a decimal (X.X)
        # Skip if it's part of a word (e.g., "v2")
        # Skip single digits
        # Skip if already processed (contains our separator)

        def replace_digit_sequence(match):
            full_match = match.group(0)
            start = match.start()
            end = match.end()
            before = match.string[max(0, start-3):start]
            after = match.string[end:end+3]

            # Skip if part of a phone number (preceded or followed by pause markers)
            if before.endswith('...') or after.startswith('...'):
                return full_match

            # Skip if preceded by $ (price)
            if match.string[max(0, start-1):start] == '$':
                return full_match

            # Skip if followed by % (percentage)
            if match.string[end:end+1] == '%':
                return full_match

            # Skip if it contains a decimal point (already processed or decimal number)
            if '.' in full_match and not full_match.replace('.', '').isdigit():
                return full_match

            # Skip if preceded by letter (part of identifier like "v2")
            if match.string[max(0, start-1):start].isalpha():
                return full_match

            # Skip if followed by letter
            if match.string[end:end+1].isalpha():
                return full_match

            # Skip single or double digits (likely intentional numbers like "5 stars")
            if len(full_match) <= 2:
                return full_match

            # Format as digit-by-digit
            return self._format_digit_group(full_match)

        # Match sequences of 3+ digits that aren't already formatted
        # Negative lookbehind for $ and letters
        text = re.sub(
            r'(?<![,$\w])(\d{3,})(?![%\w])',
            replace_digit_sequence,
            text
        )

        return text

    def format_digits(self, number_str: str) -> str:
        """
        Manually format a number string as digit-by-digit.

        Args:
            number_str: String of digits (e.g., "248")

        Returns:
            Formatted string (e.g., "2, 4, 8")
        """
        digits_only = ''.join(c for c in number_str if c.isdigit())
        return self._format_digit_group(digits_only)


# Default preprocessor instance
default_preprocessor = TextPreprocessor()


def preprocess_script(text: str) -> str:
    """
    Convenience function to preprocess script text with default settings.

    Args:
        text: Original script text

    Returns:
        Preprocessed text
    """
    return default_preprocessor.preprocess(text)
