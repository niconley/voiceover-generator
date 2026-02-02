"""
Flask web application for bulk voiceover generation.
"""
import sys
from pathlib import Path
import os
from datetime import datetime
import threading
import uuid
import zipfile

from flask import Flask, render_template, request, jsonify, send_file, session
from flask_cors import CORS
from werkzeug.utils import secure_filename

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config.settings import Config
from backend.src.workflow.orchestrator import VoiceoverOrchestrator
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

# Configuration
UPLOAD_FOLDER = Config.UPLOAD_FOLDER
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
app.config['MAX_CONTENT_LENGTH'] = Config.MAX_CONTENT_LENGTH

# Allowed file extensions
ALLOWED_EXTENSIONS = {'csv', 'xlsx', 'xls'}

# Global storage for batch status (in production, use Redis or database)
batch_status = {}
batch_results = {}
batch_models = {}  # Store model selection per batch


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
    model = request.form.get('model', 'eleven_multilingual_v2')

    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Only CSV and Excel files allowed.'}), 400

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

        # Store file path and model in session
        session[f'file_{batch_id}'] = str(filepath)
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
        # Get file path from session
        filepath = session.get(f'file_{batch_id}')

        if not filepath or not Path(filepath).exists():
            return jsonify({'error': 'Batch file not found'}), 404

        # Get model from request body or stored selection
        data = request.get_json() or {}
        model = data.get('model') or batch_models.get(batch_id, 'eleven_multilingual_v2')

        # Initialize orchestrator with selected model
        orchestrator = VoiceoverOrchestrator(model=model)

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

        # Create temporary zip file
        zip_path = Path(app.config['UPLOAD_FOLDER']) / f'{batch_id}_{folder}.zip'

        with zipfile.ZipFile(zip_path, 'w') as zipf:
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

        return send_file(
            str(zip_path),
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

    # Map model to template file
    template_map = {
        'eleven_multilingual_v2': 'voiceover_template_v2.csv',
        'eleven_v3': 'voiceover_template_v3.csv',
        'eleven_turbo_v2_5': 'voiceover_template_v2.csv',  # Same as V2
    }

    template_file = template_map.get(model, 'voiceover_template_v2.csv')
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
