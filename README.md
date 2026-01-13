# Bulk Voiceover Generator

A professional-grade tool for generating commercial voiceovers in bulk with precise timing control using the ElevenLabs API.

## Features

- **Precise Timing Control**: Generate voiceovers that match exact durations (±0.3s tolerance)
- **Bulk Processing**: Process dozens of scripts in one batch from CSV/Excel files
- **Automated Quality Control**:
  - Duration accuracy verification
  - Audio clipping detection
  - Silence detection
  - Speech-to-text verification (using Whisper)
- **Intelligent Retry Logic**: Automatically adjusts speed and retries to hit target durations
- **Dual Interface**: Command-line and web UI for flexibility
- **Comprehensive Reporting**: Detailed CSV/JSON reports with quality metrics

## Requirements

- Python 3.11+
- FFmpeg (for audio processing)
- ElevenLabs API key

## Installation

### 1. Install System Dependencies

**macOS:**
```bash
brew install ffmpeg
```

**Ubuntu/Debian:**
```bash
sudo apt-get install ffmpeg
```

**Windows:**
Download FFmpeg from [ffmpeg.org](https://ffmpeg.org/download.html)

### 2. Clone and Setup

```bash
cd "New Claude code project"

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
# venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit .env and add your ElevenLabs API key
# ELEVENLABS_API_KEY=sk_your_api_key_here
```

## Quick Start

### Command-Line Interface

#### 1. Create a Template CSV

```bash
python backend/main.py create-template
```

This creates `input_templates/voiceover_template.csv` with example data.

#### 2. Edit the CSV

Open the template and add your scripts:

```csv
script_text,target_duration,voice_id,voice_name,output_filename,notes
"Welcome to our product.",7.0,,Rachel,welcome.mp3,Landing page
"Limited time offer!",5.0,,Rachel,promo.mp3,Banner ad
```

**Required columns:**
- `script_text`: The text to convert to speech
- `target_duration`: Target duration in seconds
- `output_filename`: Name for the output MP3 file

**Optional columns:**
- `voice_id`: ElevenLabs voice ID (if blank, uses voice_name)
- `voice_name`: Voice name to look up
- `stability`, `similarity_boost`, `style`, `speed`: Voice settings
- `notes`: Your notes (not processed)

#### 3. List Available Voices

```bash
python backend/main.py list-voices
python backend/main.py list-voices --save backend/config/voices.yaml
```

#### 4. Validate Your Input

```bash
python backend/main.py validate -i your_input.csv
```

#### 5. Generate Voiceovers

```bash
python backend/main.py generate -i your_input.csv
```

**Options:**
- `-i, --input`: Input CSV/Excel file (required)
- `-o, --output-dir`: Output directory (default: output/)
- `-r, --max-retries`: Max retry attempts per item (default: 3)
- `--dry-run`: Validate input without generating
- `-v, --verbose`: Enable verbose logging

### Web Interface

#### 1. Start the Web Server

```bash
python frontend/app.py
```

The server will start at `http://localhost:5000`

#### 2. Upload Your CSV

1. Open http://localhost:5000 in your browser
2. Drag and drop your CSV file or click "Browse Files"
3. Review the validation summary
4. Click "Generate Voiceovers"

#### 3. View Results

After processing completes, you'll see:
- Summary statistics (completed, failed, needs review)
- Download buttons for each category
- Detailed results table with quality metrics
- CSV report download

## How It Works

### Timing Control Workflow

1. **Initial Generation**: Generate audio at normal speed (1.0x)
2. **Measure Duration**: Calculate actual duration using PyDub
3. **Check Tolerance**: Is it within ±0.3s of target?
4. **Adjust Speed** (if needed):
   - Calculate: `new_speed = current_speed * (current_duration / target_duration)`
   - Clamp to ElevenLabs range (0.7x - 1.2x)
5. **Retry**: Regenerate with adjusted speed (up to 3 attempts)
6. **Quality Checks**: Run all QC checks on final audio
7. **Organize Output**: Move to appropriate folder based on status

### Quality Control Pipeline

Every generated audio goes through:

1. **Duration Check**: Within ±0.3s of target?
2. **Clipping Detection**: <0.5% clipped samples?
3. **Silence Detection**: <10% silence?
4. **Speech Verification**: Transcribe with Whisper, compare to original (>95% accuracy)

Files are categorized as:
- **completed/**: All checks passed
- **needs_review/**: Some checks failed but audio generated
- **failed/**: Generation failed or max retries exceeded

## Output Structure

```
output/
├── completed/          # Successfully generated files
│   ├── welcome.mp3
│   └── promo.mp3
├── failed/             # Failed generations
└── needs_review/       # Quality issues detected
    └── call_to_action.mp3

logs/
├── generation.log      # Detailed logs
└── report_BATCH_ID_TIMESTAMP.csv  # Detailed report
```

## Configuration

Edit `backend/config/settings.py` or set environment variables:

```python
# Timing Settings
DURATION_TOLERANCE = 0.3  # ±0.3 seconds
SPEED_MIN = 0.7           # Minimum speed multiplier
SPEED_MAX = 1.2           # Maximum speed multiplier

# Quality Thresholds
MAX_CLIPPING_PERCENTAGE = 0.5      # 0.5% max clipping
MAX_SILENCE_RATIO = 0.1            # 10% max silence
MIN_VERIFICATION_ACCURACY = 95.0   # 95% min word accuracy

# Retry Settings
MAX_RETRIES = 3
```

## Advanced Usage

### Custom Voice Settings

Adjust voice parameters in your CSV:

```csv
script_text,target_duration,voice_name,stability,similarity_boost,style,output_filename
"Professional announcement",10.0,Rachel,0.7,0.9,0.0,announcement.mp3
"Energetic promo",5.0,Josh,0.4,0.8,0.3,energetic_promo.mp3
```

**Parameters:**
- `stability` (0-1): Higher = more consistent, lower = more variable
- `similarity_boost` (0-1): Higher = closer to original voice
- `style` (0-1): Higher = more expressive (may increase latency)
- `speed` (0.7-1.2): Initial speed (will be adjusted automatically)

### Voice Browser Utility

```python
from backend.src.utils.voice_browser import VoiceBrowser
from backend.src.api.elevenlabs_client import ElevenLabsClient

client = ElevenLabsClient(api_key="your_key")
browser = VoiceBrowser(client)

# List all voices
voices_df = browser.list_voices()
print(voices_df)

# Search for voices
results = browser.search_voices("commercial")

# Get recommendations
recommendations = browser.recommend_voice(
    use_case="commercial",
    gender="female",
    accent="american"
)

# Generate preview
audio = browser.preview_voice(
    voice_id="21m00Tcm4TlvDq8ikWAM",
    sample_text="This is a test.",
    output_path="preview.mp3"
)
```

## Troubleshooting

### Issue: "ELEVENLABS_API_KEY is not set"

**Solution**: Create `.env` file with your API key:
```bash
cp .env.example .env
# Edit .env and add: ELEVENLABS_API_KEY=sk_your_key_here
```

### Issue: "FFmpeg not found"

**Solution**: Install FFmpeg:
```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt-get install ffmpeg
```

### Issue: Timing always outside tolerance

**Possible causes:**
1. Script too long/short for target duration
2. Speed adjustments hitting limits (0.7-1.2)

**Solution**:
- Adjust script length (add/remove words)
- Use more realistic target durations
- Check logs for speed adjustment details

### Issue: High verification failure rate

**Possible causes:**
1. Poor audio quality
2. Complex words/numbers
3. Whisper model mismatch

**Solution**:
- Use higher quality Whisper model: `WHISPER_MODEL=small` in `.env`
- Simplify script text
- Check "needs_review" folder audio manually

## Performance

- **Average processing time**: 30-60s per voiceover (including retries)
- **API rate limits**: Respects ElevenLabs rate limits with exponential backoff
- **Concurrent processing**: Up to 5 concurrent API requests (configurable)
- **Memory usage**: ~500MB base + Whisper model (~500MB for "base" model)

## API Costs

ElevenLabs charges based on character count:
- Calculate cost: `characters * rate_per_character`
- Use `estimate_character_cost()` to preview costs
- Check subscription usage with `get_subscription_info()`

## Development

### Running Tests

```bash
pytest tests/
pytest tests/ --cov=backend/src --cov-report=html
```

### Project Structure

```
├── backend/
│   ├── config/              # Configuration
│   ├── src/
│   │   ├── api/            # ElevenLabs API client
│   │   ├── audio/          # Audio processing & QC
│   │   ├── verification/   # Timing & speech verification
│   │   ├── workflow/       # Orchestration & I/O
│   │   └── utils/          # Utilities
│   └── main.py             # CLI entry point
├── frontend/
│   ├── app.py              # Flask web server
│   ├── templates/          # HTML templates
│   └── static/             # CSS/JS assets
├── output/                 # Generated audio files
├── logs/                   # Logs and reports
└── input_templates/        # CSV templates
```

## License

This project is provided as-is for commercial voiceover generation.

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review logs in `logs/generation.log`
3. Check ElevenLabs API status
4. Verify your API key and subscription limits

## Acknowledgments

- **ElevenLabs**: TTS API
- **OpenAI Whisper**: Speech recognition
- **PyDub**: Audio processing
- **Flask**: Web framework
