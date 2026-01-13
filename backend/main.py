"""
CLI interface for bulk voiceover generation.
"""
import sys
from pathlib import Path
import click
from tqdm import tqdm

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config.settings import Config
from backend.src.workflow.orchestrator import VoiceoverOrchestrator
from backend.src.utils.logger import setup_logging


@click.group()
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
@click.pass_context
def cli(ctx, verbose):
    """
    Bulk Voiceover Generator - Generate commercial voiceovers with precise timing control.
    """
    # Setup logging
    log_level = "DEBUG" if verbose else Config.LOG_LEVEL
    setup_logging(
        log_level=log_level,
        log_file=Config.LOG_FILE,
        log_to_console=True,
        log_to_file=True
    )

    # Store config in context
    ctx.ensure_object(dict)
    ctx.obj['config'] = Config()
    ctx.obj['verbose'] = verbose


@cli.command()
@click.option(
    '--input', '-i',
    'input_file',
    required=True,
    type=click.Path(exists=True),
    help='Input CSV or Excel file'
)
@click.option(
    '--output-dir', '-o',
    type=click.Path(),
    default=None,
    help='Output directory (default: output/)'
)
@click.option(
    '--max-retries', '-r',
    type=int,
    default=None,
    help='Maximum retry attempts per item'
)
@click.option(
    '--dry-run',
    is_flag=True,
    help='Validate input without generating'
)
@click.pass_context
def generate(ctx, input_file, output_dir, max_retries, dry_run):
    """
    Generate voiceovers from CSV/Excel file.

    Example:
        python backend/main.py generate -i input.csv
    """
    config = ctx.obj['config']

    # Override output directory if provided
    if output_dir:
        config.OUTPUT_DIR = Path(output_dir)

    try:
        # Initialize orchestrator
        orchestrator = VoiceoverOrchestrator(config)

        if dry_run:
            # Validate only
            click.echo("Validating input file...")
            result = orchestrator.validate_input(input_file)

            if result['is_valid']:
                click.secho("✓ Input file is valid", fg='green')
                click.echo(f"\nSummary:")
                for key, value in result['summary'].items():
                    click.echo(f"  {key}: {value}")
            else:
                click.secho("✗ Input file validation failed", fg='red')
                click.echo("\nErrors:")
                for error in result['errors']:
                    click.echo(f"  - {error}", err=True)
                sys.exit(1)
        else:
            # Generate voiceovers
            click.echo(f"Starting batch generation from: {input_file}")

            # Create progress bar
            progress_bar = None

            def progress_callback(current, total, item):
                nonlocal progress_bar
                if progress_bar is None:
                    progress_bar = tqdm(total=total, desc="Generating", unit="item")
                progress_bar.update(1)
                progress_bar.set_postfix_str(f"{item.filename} ({item.status})")

            # Process batch
            batch_result = orchestrator.process_batch(
                input_file=input_file,
                max_retries=max_retries,
                progress_callback=progress_callback
            )

            if progress_bar:
                progress_bar.close()

            # Display summary
            click.echo("\n" + "=" * 60)
            click.echo(batch_result.get_summary())
            click.echo("=" * 60)

            # Display output locations
            click.echo(f"\nOutput directories:")
            click.echo(f"  Completed: {config.OUTPUT_COMPLETED_DIR}")
            click.echo(f"  Failed: {config.OUTPUT_FAILED_DIR}")
            click.echo(f"  Needs Review: {config.OUTPUT_NEEDS_REVIEW_DIR}")
            click.echo(f"  Reports: {config.LOGS_DIR}")

            # Success/failure status
            if batch_result.failed_items > 0:
                sys.exit(1)

    except Exception as e:
        click.secho(f"Error: {e}", fg='red', err=True)
        if ctx.obj['verbose']:
            import traceback
            traceback.print_exc()
        sys.exit(1)


@cli.command()
@click.option(
    '--input', '-i',
    'input_file',
    required=True,
    type=click.Path(exists=True),
    help='Input CSV or Excel file to validate'
)
@click.pass_context
def validate(ctx, input_file):
    """
    Validate input file without generating.

    Example:
        python backend/main.py validate -i input.csv
    """
    config = ctx.obj['config']

    try:
        orchestrator = VoiceoverOrchestrator(config)

        click.echo(f"Validating: {input_file}")

        result = orchestrator.validate_input(input_file)

        if result['is_valid']:
            click.secho("✓ Input file is valid", fg='green')

            summary = result['summary']
            click.echo(f"\nSummary:")
            click.echo(f"  Total items: {summary['total_items']}")
            click.echo(f"  Valid items: {summary['valid_items']}")
            click.echo(f"  Invalid items: {summary['invalid_items']}")
            click.echo(f"  Total duration: {summary['total_duration']:.1f}s")

        else:
            click.secho("✗ Input file has errors", fg='red')

            click.echo(f"\nErrors found:")
            for error in result['errors']:
                click.echo(f"  - {error}", err=True)

            sys.exit(1)

    except Exception as e:
        click.secho(f"Error: {e}", fg='red', err=True)
        sys.exit(1)


@cli.command()
@click.option(
    '--save',
    type=click.Path(),
    help='Save voice list to YAML file'
)
@click.pass_context
def list_voices(ctx, save):
    """
    List available voices from ElevenLabs account.

    Example:
        python backend/main.py list-voices
        python backend/main.py list-voices --save voices.yaml
    """
    config = ctx.obj['config']

    try:
        orchestrator = VoiceoverOrchestrator(config)

        click.echo("Fetching available voices...")
        voices = orchestrator.get_available_voices()

        click.echo(f"\nFound {len(voices)} voices:\n")

        for voice in voices:
            click.echo(f"  Name: {voice['name']}")
            click.echo(f"  ID: {voice['id']}")
            if voice.get('description'):
                click.echo(f"  Description: {voice['description']}")
            click.echo()

        if save:
            import yaml
            save_path = Path(save)
            save_path.parent.mkdir(parents=True, exist_ok=True)

            voice_data = {
                'voices': {
                    voice['name'].lower().replace(' ', '_'): {
                        'id': voice['id'],
                        'name': voice['name'],
                        'description': voice.get('description', ''),
                        'category': voice.get('category', '')
                    }
                    for voice in voices
                }
            }

            with open(save_path, 'w') as f:
                yaml.dump(voice_data, f, default_flow_style=False)

            click.secho(f"✓ Saved voice list to: {save_path}", fg='green')

    except Exception as e:
        click.secho(f"Error: {e}", fg='red', err=True)
        sys.exit(1)


@cli.command()
@click.pass_context
def config_info(ctx):
    """
    Display current configuration.

    Example:
        python backend/main.py config-info
    """
    config = ctx.obj['config']

    click.echo(config.get_summary())


@cli.command()
@click.option(
    '--template', '-t',
    type=click.Path(),
    default='input_templates/voiceover_template.csv',
    help='Path to save template CSV file'
)
def create_template(template):
    """
    Create a template CSV file for input.

    Example:
        python backend/main.py create-template
        python backend/main.py create-template -t my_template.csv
    """
    import pandas as pd

    template_path = Path(template)
    template_path.parent.mkdir(parents=True, exist_ok=True)

    # Create sample data
    data = {
        'script_text': [
            'Welcome to our product. This is an amazing solution.',
            'Limited time offer - act now and save fifty percent!',
            'Call us today at one eight hundred five five five one two three four.'
        ],
        'target_duration': [7.0, 5.0, 6.5],
        'voice_id': ['', '', ''],
        'voice_name': ['Rachel', 'Rachel', 'Rachel'],
        'output_filename': ['welcome.mp3', 'promo.mp3', 'call_to_action.mp3'],
        'stability': [0.5, 0.6, 0.5],
        'similarity_boost': [0.75, 0.8, 0.75],
        'style': [0.0, 0.2, 0.0],
        'speed': [1.0, 1.0, 1.0],
        'notes': ['Landing page', 'Promo banner', 'Contact page']
    }

    df = pd.DataFrame(data)
    df.to_csv(template_path, index=False)

    click.secho(f"✓ Created template: {template_path}", fg='green')
    click.echo(f"\nEdit the template with your scripts and run:")
    click.echo(f"  python backend/main.py generate -i {template_path}")


if __name__ == '__main__':
    cli()
