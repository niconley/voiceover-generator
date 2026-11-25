"""
Flask web application for bulk voiceover generation.
"""
import sys
from pathlib import Path
import os
import hmac
import time
from datetime import datetime, timedelta
import threading
import uuid
import zipfile
import base64
import io
from urllib.parse import urlsplit

import yaml
from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for
from flask_cors import CORS
from werkzeug.utils import secure_filename

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config.settings import Config
from backend.src.workflow.orchestrator import VoiceoverOrchestrator
from backend.src.api.elevenlabs_client import ElevenLabsClient
from backend.src.audio.processor import AudioProcessor
from backend.src.utils.text_preprocessor import TextPreprocessor
from backend.src.utils.logger import setup_logging

# Initialize Flask app
app = Flask(__name__)
app.secret_key = Config.SECRET_KEY
CORS(app)

# Setup logging
setup_logging(
    log_level=Config.LOG_LEVEL,
    log_file=Config.LOG_FILE,
    log_to_console=True,
    log_to_file=True
)

if not Config.SECRET_KEY_FROM_ENV:
    app.logger.warning(
        "SECRET_KEY is not set: using a random key, so everyone is logged out "
        "whenever the server restarts. Set SECRET_KEY in the environment."
    )

# Configuration
UPLOAD_FOLDER = Config.UPLOAD_FOLDER
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
app.config['MAX_CONTENT_LENGTH'] = Config.MAX_CONTENT_LENGTH

# Login session cookie
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=Config.SESSION_LIFETIME_DAYS)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = Config.SESSION_COOKIE_SECURE

# Allowed file extensions
ALLOWED_EXTENSIONS = {'csv', 'xlsx'}

# Global storage for batch status (in production, use Redis or database)
batch_status = {}
batch_results = {}
batch_models = {}  # Store model selection per batch
batch_files = {}  # Uploaded input file path per batch (kept server-side, not in the cookie)
batch_start_lock = threading.Lock()


def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def process_batch_async(batch_id, input_file, orchestrator):
    """Process batch in background thread."""
    try:
        batch_status[batch_id] = {
            'status': 'processing',
            'current': 0,
            'total': 0,
            'message': 'Starting...'
        }

        def progress_callback(current, total, item):
            batch_status[batch_id].update({
                'current': current,
                'total': total,
                'message': f'Processing {item.filename}...'
            })

        result = orchestrator.process_batch(
            input_file=input_file,
            progress_callback=progress_callback,
            batch_id=batch_id
        )

        batch_status[batch_id] = {
            'status': 'completed',
            'current': result.total_items,
            'total': result.total_items,
            'message': 'Batch processing completed'
        }

        batch_results[batch_id] = result

    except Exception as e:
        batch_status[batch_id] = {
            'status': 'error',
            'message': str(e)
        }


# ==================== Password protection ====================

# Endpoints reachable without logging in. /health stays open for the AWS health check.
PUBLIC_ENDPOINTS = {'login', 'health_check', 'static'}


@app.before_request
def require_login():
    """Send anyone without a logged-in session to the login page."""
    if request.endpoint in PUBLIC_ENDPOINTS or session.get('authenticated'):
        return None

    # Browser page loads get redirected; API calls from the page's JavaScript get a 401.
    if request.method == 'GET' and 'text/html' in request.headers.get('Accept', ''):
        return redirect(url_for('login', next=request.full_path.rstrip('?')))
    return jsonify({'error': 'Login required. Reload the page to sign in.'}), 401


def safe_next_url(target):
    """Only allow redirects back to a path on this site (no open redirects)."""
    if (
        target
        and target.startswith('/')
        and not target.startswith('//')
        and '\\' not in target
        and not any(ord(ch) < 0x20 or ord(ch) == 0x7f for ch in target)
    ):
        parts = urlsplit(target)
        if not parts.scheme and not parts.netloc:
            return target
    return url_for('index')


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Shared-password login page."""
    next_url = safe_next_url(request.values.get('next'))

    if not Config.APP_PASSWORD:
        app.logger.error("APP_PASSWORD is not set; refusing all logins")
        return render_template(
            'login.html',
            error='Password protection is not configured on the server. Ask an admin to set APP_PASSWORD.',
            next_url=next_url
        ), 503

    if session.get('authenticated'):
        return redirect(next_url)

    if request.method == 'POST':
        password = request.form.get('password', '')
        if hmac.compare_digest(password.encode('utf-8'), Config.APP_PASSWORD.encode('utf-8')):
            session.clear()
            session.permanent = True
            session['authenticated'] = True
            return redirect(next_url)

        app.logger.warning(f"Failed login attempt from {request.headers.get('X-Forwarded-For', request.remote_addr)}")
        time.sleep(1)  # slow down password guessing
        return render_template('login.html', error='Incorrect password.', next_url=next_url), 401

    return render_template('login.html', error=None, next_url=next_url)


@app.route('/logout')
def logout():
    """Clear the session and return to the login page."""
    session.clear()
    return redirect(url_for('login'))


def resolve_model(model):
    """Return model if it's one we support, otherwise the V2 Multilingual default."""
    if model in Config.SUPPORTED_MODELS:
        return model
    return Config.ELEVENLABS_MULTILINGUAL_MODEL


@app.route('/')
def index():
    """Main upload page."""
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle file upload and validation."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    model = resolve_model(request.form.get('model'))

    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Upload a .csv or .xlsx file.'}), 400

    try:
        # Save uploaded file
        filename = secure_filename(file.filename)
        batch_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        save_filename = f"{batch_id}_{timestamp}_{filename}"
        filepath = Path(app.config['UPLOAD_FOLDER']) / save_filename

        file.save(str(filepath))

        # Validate file
        orchestrator = VoiceoverOrchestrator()
        validation_result = orchestrator.validate_input(str(filepath))

        if not validation_result['is_valid']:
            # Delete invalid file
            filepath.unlink()
            return jsonify({
                'error': 'Invalid input file',
                'details': validation_result['errors']
            }), 400

        # Remember the file and model for this batch on the server
        batch_files[batch_id] = str(filepath)
        batch_models[batch_id] = model

        return jsonify({
            'success': True,
            'batch_id': batch_id,
            'filename': filename,
            'model': model,
            'summary': validation_result['summary']
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/generate/<batch_id>', methods=['POST'])
def generate_batch(batch_id):
    """Start batch generation."""
    try:
        filepath = batch_files.get(batch_id)

        if not filepath or not Path(filepath).exists():
            return jsonify({'error': 'Upload not found. The server may have restarted; please upload the file again.'}), 404

        # Get model from request body or stored selection
        data = request.get_json() or {}
        model = resolve_model(data.get('model') or batch_models.get(batch_id))

        # Initialize orchestrator with selected model
        orchestrator = VoiceoverOrchestrator(model=model)

        # Only start each batch once (guards against double-clicks and re-sent requests)
        with batch_start_lock:
            if batch_id in batch_status:
                return jsonify({'error': 'This batch has already been started'}), 409
            batch_status[batch_id] = {
                'status': 'processing',
                'current': 0,
                'total': 0,
                'message': 'Starting...'
            }

        # Start background processing
        thread = threading.Thread(
            target=process_batch_async,
            args=(batch_id, filepath, orchestrator)
        )
        thread.daemon = True
        thread.start()

        return jsonify({
            'success': True,
            'batch_id': batch_id,
            'model': model,
            'message': 'Batch processing started'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/status/<batch_id>')
def get_status(batch_id):
    """Get batch processing status."""
    if batch_id not in batch_status:
        return jsonify({'error': 'Batch not found'}), 404

    return jsonify(batch_status[batch_id])


@app.route('/results/<batch_id>')
def get_results(batch_id):
    """Get batch results."""
    if batch_id not in batch_results:
        # Check if still processing
        if batch_id in batch_status:
            status = batch_status[batch_id]
            if status.get('status') == 'error':
                return jsonify({'error': status.get('message', 'Batch failed')}), 500
            return jsonify({
                'processing': True,
                'status': status
            })
        else:
            return jsonify({'error': 'Batch not found'}), 404

    result = batch_results[batch_id]

    return jsonify({
        'batch_id': result.batch_id,
        'timestamp': result.timestamp.isoformat(),
        'total_items': result.total_items,
        'completed': result.completed_items,
        'failed': result.failed_items,
        'needs_review': result.review_items,
        'total_duration': result.total_duration,
        'results': [r.to_dict() for r in result.results]
    })


@app.route('/results/<batch_id>/page')
def results_page(batch_id):
    """Display results page."""
    if batch_id not in batch_results and batch_id not in batch_status:
        return "Batch not found", 404

    return render_template('results.html', batch_id=batch_id)


@app.route('/download/<batch_id>/<folder>')
def download_folder(batch_id, folder):
    """Download files from a specific batch as zip."""
    if batch_id not in batch_results:
        return "Batch not found", 404

    if folder not in ['completed', 'failed', 'needs_review', 'all']:
        return "Invalid folder", 400

    try:
        # Get the batch results for this specific batch
        batch = batch_results[batch_id]

        # Build the zip in memory so simultaneous downloads can't clobber each other
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, 'w') as zipf:
            # Only include files from this batch
            for result in batch.results:
                # Skip if no audio path (failed before generation)
                if not result.audio_path or not Path(result.audio_path).exists():
                    continue

                # Filter by folder type
                if folder == 'all':
                    # Include all files
                    zipf.write(result.audio_path, f'{result.status}/{result.filename}')
                elif result.status == folder:
                    # Include only files matching the requested status
                    zipf.write(result.audio_path, result.filename)

            # Add report
            if folder == 'all':
                result = batch_results[batch_id]
                timestamp = result.timestamp.strftime('%Y%m%d_%H%M%S')
                report_path = Config.LOGS_DIR / f"report_{batch_id}_{timestamp}.csv"
                if report_path.exists():
                    zipf.write(report_path, 'report.csv')

        zip_buffer.seek(0)
        return send_file(
            zip_buffer,
            as_attachment=True,
            download_name=f'{batch_id}_{folder}.zip',
            mimetype='application/zip'
        )

    except Exception as e:
        return f"Error creating download: {e}", 500


@app.route('/download/<batch_id>/report')
def download_report(batch_id):
    """Download CSV report."""
    if batch_id not in batch_results:
        return "Batch not found", 404

    try:
        result = batch_results[batch_id]
        timestamp = result.timestamp.strftime('%Y%m%d_%H%M%S')
        report_path = Config.LOGS_DIR / f"report_{batch_id}_{timestamp}.csv"

        if not report_path.exists():
            return "Report not found", 404

        return send_file(
            str(report_path),
            as_attachment=True,
            download_name=f'report_{batch_id}.csv',
            mimetype='text/csv'
        )

    except Exception as e:
        return f"Error downloading report: {e}", 500


@app.route('/template/<model>')
def download_template(model):
    """Download CSV template for the selected model."""
    templates_dir = Path(__file__).parent.parent / 'input_templates'

    template_file = Config.SUPPORTED_MODELS[resolve_model(model)]
    template_path = templates_dir / template_file

    if not template_path.exists():
        return "Template not found", 404

    return send_file(
        str(template_path),
        as_attachment=True,
        download_name=template_file,
        mimetype='text/csv'
    )


@app.route('/voices')
def get_voices():
    """Get available voices."""
    try:
        orchestrator = VoiceoverOrchestrator()
        voices = orchestrator.get_available_voices()

        return jsonify({
            'success': True,
            'voices': voices
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/voices/local')
def get_local_voices():
    """Get curated voice list from local YAML config (no API call needed)."""
    try:
        voices_path = Path(__file__).parent.parent / 'backend' / 'config' / 'my_voices.yaml'
        with open(voices_path) as f:
            data = yaml.safe_load(f)

        voices = [
            {
                'id': v['id'],
                'name': v['name'],
                'category': v.get('category', ''),
                'description': v.get('description', '')
            }
            for v in data.get('voices', {}).values()
        ]
        voices.sort(key=lambda v: v['name'])

        return jsonify({'success': True, 'voices': voices})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/preview', methods=['POST'])
def preview_duration():
    """Generate a real audio sample and return its measured duration + audio data."""
    try:
        data = request.get_json()
        script_text = (data.get('script_text') or '').strip()
        voice_id = (data.get('voice_id') or '').strip()
        model = resolve_model(data.get('model'))

        if not script_text:
            return jsonify({'error': 'Script text is required'}), 400
        if not voice_id:
            return jsonify({'error': 'Voice is required'}), 400
        if not Config.ELEVENLABS_API_KEY:
            return jsonify({'error': 'ElevenLabs API key not configured'}), 500

        client = ElevenLabsClient(api_key=Config.ELEVENLABS_API_KEY, default_model=model)
        processor = AudioProcessor(
            default_format=Config.AUDIO_FORMAT,
            default_bitrate=Config.BITRATE
        )
        preprocessor = TextPreprocessor()

        processed_text = preprocessor.preprocess(script_text)
        audio_data = client.generate_speech(
            text=processed_text,
            voice_id=voice_id,
            model=model
        )

        audio_data = processor.trim_silence(
            audio_data,
            silence_threshold=Config.SILENCE_THRESHOLD,
            padding_ms=Config.SILENCE_PADDING_MS
        )
        duration = processor.get_duration(audio_data)

        return jsonify({
            'success': True,
            'duration': round(duration, 2),
            'audio_b64': base64.b64encode(audio_data).decode('utf-8')
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/health')
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    })


if __name__ == '__main__':
    app.run(
        host=Config.FLASK_HOST,
        port=Config.FLASK_PORT,
        debug=Config.FLASK_DEBUG
    )
