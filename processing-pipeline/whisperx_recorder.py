#!/usr/bin/env python3
"""
WhisperX Recording Controller

This script handles:
- OBS recording control via obs-cmd
- Meeting title input and file organization
- Metadata generation
- Audio extraction and WhisperX transcription
- LLM-based analysis (OpenAI or Anthropic) of transcripts

Configuration:
- Defaults: processing-pipeline/config.default.json (version controlled)
- User overrides: ~/.config/whisperx/settings.json (personal settings)
"""

import functools
import io
import json
import logging
import os
import re
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

# ─── Configuration Management ─────────────────────────────────────────────────

# Config paths
SCRIPT_DIR = Path(__file__).parent
DEFAULT_CONFIG_FILE = SCRIPT_DIR / "config.default.json"
USER_CONFIG_DIR = Path.home() / ".config/whisperx"
USER_SETTINGS_FILE = USER_CONFIG_DIR / "settings.json"
STATE_FILE = USER_CONFIG_DIR / "recording_state.json"
PROCESSING_STATE_FILE = USER_CONFIG_DIR / "processing_state.json"
LOG_DIR = USER_CONFIG_DIR / "logs"
LOG_FILE = LOG_DIR / "whisperx_recorder.log"

# SwiftBar's terminal=false launches run with launchd's minimal PATH, which
# omits Homebrew and ~/.local/bin - so bare subprocess calls to obs-cmd/op
# below fail to resolve even though they work fine from an interactive shell.
for _bin_dir in ('/opt/homebrew/bin', str(Path.home() / '.local/bin')):
    if _bin_dir not in os.environ.get('PATH', '').split(os.pathsep):
        os.environ['PATH'] = _bin_dir + os.pathsep + os.environ.get('PATH', '')


# ─── Logging Setup ────────────────────────────────────────────────────────────

def setup_logging(verbose: bool = False):
    """Configure logging to file and optionally console."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # File handler - always log to file
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    
    # Console handler - only if verbose or running interactively
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO if verbose else logging.WARNING)
    console_handler.setFormatter(formatter)
    
    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    
    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


# Initialize logging
logger = setup_logging()


def deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dicts, with override taking precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def expand_path(path_str: str) -> Path:
    """Expand ~ and environment variables in path."""
    return Path(os.path.expandvars(os.path.expanduser(path_str)))


def resolve_secret(value: str) -> str:
    """Resolve a config value that may be an op:// 1Password reference or a
    keychain:// macOS Keychain reference. Other values pass through unchanged."""
    if not value:
        return value
    if value.startswith('op://'):
        return _resolve_op_reference(value)
    if value.startswith('keychain://'):
        return _resolve_keychain_reference(value)
    return value


@functools.lru_cache(maxsize=None)
def _resolve_op_reference(op_uri: str) -> str:
    result = subprocess.run(['op', 'read', op_uri], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to resolve secret from 1Password ({op_uri}): {result.stderr.strip()}\n"
            f"Make sure the 1Password CLI is installed and you're signed in (op signin)."
        )
    return result.stdout.strip()


@functools.lru_cache(maxsize=None)
def _resolve_keychain_reference(keychain_uri: str) -> str:
    """Resolve a keychain://<service> reference from the login keychain (account = current user)."""
    service = keychain_uri[len('keychain://'):]
    account = os.getlogin()
    result = subprocess.run(
        ['security', 'find-generic-password', '-a', account, '-s', service, '-w'],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to resolve secret from Keychain (service={service}, account={account}): {result.stderr.strip()}\n"
            f"Add it with: security add-generic-password -a {account} -s '{service}' -w '<value>'"
        )
    return result.stdout.strip()


def load_config() -> dict:
    """
    Load configuration with cascading priority:
    1. Hardcoded defaults (fallback)
    2. config.default.json (project defaults)
    3. ~/.config/whisperx/settings.json (user overrides)
    """
    # Hardcoded fallback defaults
    config = {
        "recording": {
            "output_dir": "~/OBSRecordings",
            "obs_ws_port": "4455",
            "obs_ws_password": "",
            "keep_video": False
        },
        "transcription": {
            "diarize": False,
            "language": "en",
            "device": "cpu",
            "compute_type": "float32",
            "whisperx_path": "~/anaconda3/bin/whisperx",
            "hf_token": ""
        }
    }
    
    # Load project defaults
    if DEFAULT_CONFIG_FILE.exists():
        with open(DEFAULT_CONFIG_FILE, 'r') as f:
            project_config = json.load(f)
            # Remove comment fields
            project_config = {k: v for k, v in project_config.items() if not k.startswith('_')}
            config = deep_merge(config, project_config)
    
    # Load user overrides
    if USER_SETTINGS_FILE.exists():
        with open(USER_SETTINGS_FILE, 'r') as f:
            user_config = json.load(f)
            
            # Handle backward compatibility: migrate flat 'diarize' to nested structure
            if 'diarize' in user_config and 'transcription' not in user_config:
                user_config = {
                    'transcription': {'diarize': user_config['diarize']}
                }
                # Save migrated format
                save_user_settings(user_config)
            
            config = deep_merge(config, user_config)
    
    return config


def save_user_settings(settings: dict):
    """Save user settings to override file."""
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(USER_SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=2)


def get_user_settings() -> dict:
    """Load only user settings (not merged with defaults)."""
    if USER_SETTINGS_FILE.exists():
        with open(USER_SETTINGS_FILE, 'r') as f:
            return json.load(f)
    return {}


# Load config once at module level
_config = load_config()

# ─── Config Accessors ─────────────────────────────────────────────────────────

def get_config() -> dict:
    """Get the full merged configuration."""
    return _config


def reload_config():
    """Reload configuration from files."""
    global _config
    _config = load_config()


# Recording settings
OBS_RECORD_DIR = expand_path(_config['recording']['output_dir'])
OBS_WS_PORT = _config['recording']['obs_ws_port']
OBS_WS_PASSWORD = _config['recording']['obs_ws_password']

# Transcription settings
WHISPERX_PATH = expand_path(_config['transcription']['whisperx_path'])
HF_TOKEN = _config['transcription']['hf_token']


def get_diarize_setting() -> bool:
    """Get current diarization setting."""
    return _config['transcription'].get('diarize', False)


def get_keep_video_setting() -> bool:
    """Get current keep-video setting (preserve source video after processing)."""
    return _config['recording'].get('keep_video', False)


# ─── OpenAI Config Accessors ──────────────────────────────────────────────────

def get_llm_config() -> dict:
    """Get LLM analysis configuration."""
    return _config.get('llm', {})


def get_llm_provider() -> str:
    """Get configured LLM provider ('openai' or 'anthropic')."""
    return get_llm_config().get('provider', 'openai')


def is_llm_enabled() -> bool:
    """Check if LLM analysis is enabled and properly configured."""
    llm_config = get_llm_config()
    if not llm_config.get('enabled', False):
        return False

    provider = llm_config.get('provider', 'openai')
    if provider == 'anthropic':
        return bool(llm_config.get('anthropic_api_key'))
    else:
        return bool(llm_config.get('api_key'))


def should_auto_analyze() -> bool:
    """Whether LLM analysis should run automatically after transcription (start/stop, process).
    The transcript is the primary deliverable by default; analysis is opt-in via this setting
    or run on demand later with the `analyze` command, independent of this flag."""
    return is_llm_enabled() and get_llm_config().get('auto_analyze', False)


def get_call_types() -> dict:
    """Get all configured call types."""
    return _config.get('call_types', {})


def get_call_type(call_type_id: str) -> dict:
    """Get a specific call type configuration."""
    call_types = get_call_types()
    return call_types.get(call_type_id, call_types.get('generic', {}))


# ─── Google Drive Integration ────────────────────────────────────────────────

def get_gdrive_config() -> dict:
    """Get Google Drive configuration."""
    return _config.get('gdrive', {})


def is_gdrive_enabled() -> bool:
    """Check if Google Drive upload is enabled."""
    return get_gdrive_config().get('enabled', False)


def get_gdrive_service():
    """
    Create and return an authenticated Google Drive service.
    
    Returns:
        tuple: (service, error_message) - service is None if failed
    """
    if not is_gdrive_enabled():
        return None, "Google Drive upload not enabled"
    
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        
        gdrive_config = get_gdrive_config()
        sa_file = gdrive_config.get('service_account_file', '')
        scopes = ['https://www.googleapis.com/auth/drive']

        if sa_file.startswith('op://'):
            sa_info = json.loads(resolve_secret(sa_file))
            credentials = service_account.Credentials.from_service_account_info(
                sa_info,
                scopes=scopes
            )
        else:
            # Look for service account file in project directory
            sa_path = SCRIPT_DIR.parent / sa_file
            if not sa_path.exists():
                # Also check in processing-pipeline directory
                sa_path = SCRIPT_DIR / sa_file

            if not sa_path.exists():
                return None, f"Service account file not found: {sa_file}"

            credentials = service_account.Credentials.from_service_account_file(
                str(sa_path),
                scopes=scopes
            )
        
        service = build('drive', 'v3', credentials=credentials)
        logger.info("Google Drive service created successfully")
        return service, None
        
    except ImportError as e:
        return None, f"Google API client not installed: {e}. Run: pip install google-api-python-client google-auth"
    except Exception as e:
        logger.error(f"Failed to create Google Drive service: {e}")
        return None, str(e)


# Cache for folder IDs to avoid repeated API calls
_gdrive_folder_cache = {}


def get_or_create_gdrive_folder(service, folder_name: str, parent_id: str = None) -> Optional[str]:
    """
    Get existing folder ID or create new folder in Google Drive.
    
    Args:
        service: Google Drive service
        folder_name: Name of the folder
        parent_id: Parent folder ID (defaults to configured parent_folder_id). Works for a
            regular Drive folder shared with the service account, or a Shared Drive's ID.

    Returns:
        Folder ID or None if failed
    """
    global _gdrive_folder_cache

    gdrive_config = get_gdrive_config()
    if parent_id is None:
        parent_id = gdrive_config.get('parent_folder_id', '')

    cache_key = f"{parent_id}:{folder_name}"
    if cache_key in _gdrive_folder_cache:
        return _gdrive_folder_cache[cache_key]

    try:
        # Search for existing folder. Deliberately omits corpora='drive'/driveId, which
        # restrict the search to a Shared Drive - parent_id is usually just a regular
        # folder shared with the service account, and 'in parents' scopes correctly either way.
        query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed = false"
        results = service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name)',
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        
        files = results.get('files', [])
        if files:
            folder_id = files[0]['id']
            logger.info(f"Found existing folder: {folder_name} ({folder_id})")
            _gdrive_folder_cache[cache_key] = folder_id
            return folder_id
        
        # Create new folder
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_id]
        }
        
        folder = service.files().create(
            body=file_metadata,
            fields='id, name',
            supportsAllDrives=True
        ).execute()
        
        folder_id = folder.get('id')
        logger.info(f"Created new folder: {folder_name} ({folder_id})")
        _gdrive_folder_cache[cache_key] = folder_id
        return folder_id
        
    except Exception as e:
        logger.error(f"Failed to get/create folder '{folder_name}': {e}")
        return None


def markdown_to_html(md_content: str) -> str:
    """
    Convert markdown content to HTML for Google Docs import.
    """
    try:
        import markdown
        
        md = markdown.Markdown(extensions=[
            'tables',
            'fenced_code',
            'nl2br',
            'sane_lists',
        ])
        
        html_content = md.convert(md_content)
        
        html_doc = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
    h1, h2, h3 {{ color: #333; }}
    code {{ background-color: #f4f4f4; padding: 2px 6px; border-radius: 3px; }}
    pre {{ background-color: #f4f4f4; padding: 12px; border-radius: 5px; overflow-x: auto; }}
    blockquote {{ border-left: 4px solid #ddd; margin-left: 0; padding-left: 16px; color: #666; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
    th {{ background-color: #f4f4f4; }}
</style>
</head>
<body>
{html_content}
</body>
</html>"""
        
        return html_doc
    except ImportError:
        logger.warning("markdown library not installed, uploading as plain text")
        return md_content


def upload_to_gdrive(
    analysis_file: Path,
    call_type_name: str,
    title: str,
    analyzed_date: datetime = None
) -> Optional[str]:
    """
    Upload analysis file to Google Drive as a Google Doc.
    
    Args:
        analysis_file: Path to the analysis markdown file
        call_type_name: Human-readable call type name (e.g., "Interview: AE:FE Mgr")
        title: Meeting/interview title (person name, etc.)
        analyzed_date: When the analysis was run
    
    Returns:
        Google Doc URL or None if failed
    """
    if not is_gdrive_enabled():
        logger.debug("Google Drive upload not enabled, skipping")
        return None
    
    service, error = get_gdrive_service()
    if not service:
        logger.warning(f"Google Drive service unavailable: {error}")
        return None
    
    try:
        from googleapiclient.http import MediaIoBaseUpload
        
        gdrive_config = get_gdrive_config()
        parent_folder_id = gdrive_config.get('parent_folder_id', '')

        # Get or create folder for this call type
        folder_id = get_or_create_gdrive_folder(service, call_type_name, parent_folder_id)
        if not folder_id:
            logger.error(f"Could not get/create folder for: {call_type_name}")
            return None
        
        # Generate document name: <Call Type> <yy_mm_dd> - <title>
        if analyzed_date is None:
            analyzed_date = datetime.now()
        date_str = analyzed_date.strftime('%y_%m_%d')
        
        # Clean up title for display
        clean_title = title.replace('_', ' ') if title else 'Untitled'
        doc_name = f"{call_type_name} {date_str} - {clean_title}"
        
        # Read and convert markdown to HTML
        with open(analysis_file, 'r', encoding='utf-8') as f:
            md_content = f.read()
        
        html_content = markdown_to_html(md_content)
        
        # File metadata for Google Doc conversion
        file_metadata = {
            'name': doc_name,
            'parents': [folder_id],
            'mimeType': 'application/vnd.google-apps.document'
        }
        
        # Upload as HTML for conversion
        media = MediaIoBaseUpload(
            io.BytesIO(html_content.encode('utf-8')),
            mimetype='text/html',
            resumable=True
        )
        
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, name, webViewLink',
            supportsAllDrives=True
        ).execute()
        
        doc_url = file.get('webViewLink')
        logger.info(f"Uploaded to Google Drive: {doc_name}")
        logger.info(f"  Folder: {call_type_name}")
        logger.info(f"  URL: {doc_url}")
        
        return doc_url
        
    except Exception as e:
        logger.error(f"Failed to upload to Google Drive: {e}")
        logger.error(traceback.format_exc())
        return None


def load_pdf_content(file_path: Path) -> str:
    """
    Extract text content from a PDF file.
    
    Args:
        file_path: Path to the PDF file
    
    Returns:
        Extracted text content from all pages
    """
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        text_parts = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
        return "\n\n".join(text_parts)
    except ImportError:
        logger.warning("pypdf not installed - cannot read PDF files. Install with: pip install pypdf")
        return ""
    except Exception as e:
        logger.warning(f"Failed to extract text from PDF {file_path}: {e}")
        return ""


def load_context_files(context_file_paths: list) -> str:
    """
    Load and concatenate multiple context files.
    
    Supports text files (.md, .txt, etc.) and PDF files (.pdf).
    
    Args:
        context_file_paths: List of relative paths (e.g., 'interview/shared_context.md')
    
    Returns:
        Concatenated content of all context files
    
    Note:
        Base path is determined by 'context_base_path' in user settings.
        If not set, defaults to repo root. This allows users to maintain
        private prompt repositories separate from the main codebase.
    """
    context_parts = []
    
    # Check for custom context base path in user settings
    user_settings = get_user_settings()
    context_base = user_settings.get('context_base_path')
    
    if context_base:
        base_path = Path(context_base).expanduser()
        logger.debug(f"Using custom context base path: {base_path}")
    else:
        base_path = SCRIPT_DIR.parent  # Default: repo root
        logger.debug(f"Using default context base path: {base_path}")
    
    for file_path in context_file_paths:
        full_path = base_path / file_path
        logger.debug(f"Loading context file: {full_path}")
        
        if full_path.exists():
            try:
                # Handle PDF files
                if full_path.suffix.lower() == '.pdf':
                    content = load_pdf_content(full_path)
                    if content:
                        context_parts.append(content)
                        logger.debug(f"Loaded {len(content)} chars from PDF {file_path}")
                    else:
                        logger.warning(f"No text extracted from PDF {file_path}")
                else:
                    # Handle text files (markdown, txt, etc.)
                    with open(full_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        context_parts.append(content)
                        logger.debug(f"Loaded {len(content)} chars from {file_path}")
            except Exception as e:
                logger.warning(f"Failed to load context file {file_path}: {e}")
        else:
            logger.warning(f"Context file not found: {full_path}")
    
    if context_parts:
        combined = "\n\n---\n\n".join(context_parts)
        logger.info(f"Loaded {len(context_parts)} context file(s), total {len(combined)} chars")
        return combined
    
    return ""


def set_diarize_setting(enabled: bool):
    """Set diarization preference (saves to user settings)."""
    user_settings = get_user_settings()
    if 'transcription' not in user_settings:
        user_settings['transcription'] = {}
    user_settings['transcription']['diarize'] = enabled
    save_user_settings(user_settings)
    reload_config()
    print(f"Diarization {'enabled' if enabled else 'disabled'}")


# ─── File Naming ──────────────────────────────────────────────────────────────

def sanitize_filename(name: str) -> str:
    """Convert meeting title to a safe filename."""
    # Replace spaces and special chars with underscores
    sanitized = re.sub(r'[^\w\s-]', '', name)
    sanitized = re.sub(r'[\s]+', '_', sanitized)
    return sanitized[:50]  # Limit length


def generate_paths(meeting_title: str = None):
    """Generate all output paths for a recording session."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    time_str = datetime.now().strftime("%H%M%S")
    
    if meeting_title:
        safe_title = sanitize_filename(meeting_title)
        base_name = f"{date_str}_{safe_title}"
    else:
        base_name = f"{date_str}_Recording"
    
    filename = f"{base_name}_{time_str}"
    output_dir = OBS_RECORD_DIR / base_name
    
    return {
        'base_name': base_name,
        'filename': filename,
        'output_dir': str(output_dir),
        'transcript_dir': str(output_dir / f"{filename}_transcript"),
        'audio_file': str(output_dir / f"{filename}.wav"),
        'metadata_file': str(output_dir / f"{filename}_metadata.json"),
    }


# ─── Notifications ────────────────────────────────────────────────────────────

def notify(title: str, message: str):
    """Show macOS notification."""
    subprocess.run([
        'osascript', '-e',
        f'display notification "{message}" with title "{title}"'
    ], capture_output=True)


# ─── OBS Control ──────────────────────────────────────────────────────────────

def get_obs_cmd_args():
    """Build obs-cmd connection arguments."""
    if OBS_WS_PASSWORD:
        return f"--websocket obsws://127.0.0.1:{OBS_WS_PORT}/{resolve_secret(OBS_WS_PASSWORD)}"
    return f"-w ws://127.0.0.1:{OBS_WS_PORT}"


def is_obs_running():
    """Check if OBS is currently running."""
    result = subprocess.run(['pgrep', '-x', 'obs'], capture_output=True)
    return result.returncode == 0


def launch_obs():
    """Launch OBS application."""
    subprocess.run(['open', '-a', 'OBS'])


def start_recording() -> bool:
    """Start OBS recording. Returns True if the command reached OBS successfully."""
    args = get_obs_cmd_args().split()
    result = subprocess.run(['obs-cmd'] + args + ['recording', 'start'])
    return result.returncode == 0


def is_recording_active() -> bool:
    """Check whether OBS confirms it is actively (and not just nominally) recording.

    Catches OBS being present but unresponsive (e.g. stuck behind a blocking
    modal dialog) - `recording start` can appear to succeed while OBS never
    actually starts writing a file.
    """
    args = get_obs_cmd_args().split()
    result = subprocess.run(['obs-cmd'] + args + ['recording', 'status-active'], capture_output=True)
    return result.returncode == 0


def stop_recording():
    """Stop OBS recording."""
    args = get_obs_cmd_args().split()
    subprocess.run(['obs-cmd'] + args + ['recording', 'stop'])


def close_obs():
    """Gracefully close OBS."""
    # Use tell/quit with error handling to avoid "User canceled" dialogs
    script = '''
        try
            tell application "OBS" to quit
        end try
    '''
    subprocess.run(['osascript', '-e', script], stderr=subprocess.DEVNULL)


# ─── State Management ─────────────────────────────────────────────────────────

def save_state(state: dict):
    """Save recording state to file."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def load_state() -> dict:
    """Load recording state from file."""
    if STATE_FILE.exists():
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {}


def clear_state():
    """Clear the recording state."""
    if STATE_FILE.exists():
        STATE_FILE.unlink()


def is_recording() -> bool:
    """Check if a recording session is active."""
    state = load_state()
    return state.get('recording', False)


# ─── Processing State Management ───────────────────────────────────────────────

def _load_processing_file() -> dict:
    """Load raw processing state file."""
    if PROCESSING_STATE_FILE.exists():
        try:
            with open(PROCESSING_STATE_FILE, 'r') as f:
                return json.load(f)
        except:
            return {'jobs': []}
    return {'jobs': []}


def _save_processing_file(data: dict):
    """Save raw processing state file."""
    PROCESSING_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROCESSING_STATE_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def add_processing_job(job: dict):
    """Add a processing job to the queue."""
    data = _load_processing_file()
    if 'jobs' not in data:
        data['jobs'] = []
    data['jobs'].append(job)
    _save_processing_file(data)


def load_processing_jobs() -> list:
    """Load all active processing jobs, filtering out dead processes."""
    data = _load_processing_file()
    jobs = data.get('jobs', [])
    
    # Filter to only jobs with running processes
    active_jobs = []
    for job in jobs:
        pid = job.get('pid')
        if pid:
            try:
                os.kill(pid, 0)  # Check if process exists
                active_jobs.append(job)
            except ProcessLookupError:
                # Process finished, skip it
                pass
    
    # Update file if we removed any dead jobs
    if len(active_jobs) != len(jobs):
        _save_processing_file({'jobs': active_jobs})
    
    return active_jobs


def remove_processing_job(pid: int):
    """Remove a specific processing job by PID."""
    data = _load_processing_file()
    jobs = data.get('jobs', [])
    data['jobs'] = [j for j in jobs if j.get('pid') != pid]
    _save_processing_file(data)


def clear_all_processing_state():
    """Clear all processing state."""
    if PROCESSING_STATE_FILE.exists():
        PROCESSING_STATE_FILE.unlink()


def is_processing() -> bool:
    """Check if any processing job is active."""
    return len(load_processing_jobs()) > 0


def get_processing_count() -> int:
    """Get number of active processing jobs."""
    return len(load_processing_jobs())


# ─── Recording Session Management ─────────────────────────────────────────────

def prompt_for_recording_details() -> dict:
    """
    Prompt user for meeting details including call type.
    
    Returns:
        dict with 'title', 'call_type', and optionally 'person_name'
    """
    print()
    print("=" * 60)
    print("🎙️  WhisperX Recording")
    print("=" * 60)
    print()
    
    # Get call types
    call_types = get_call_types()
    call_type_ids = list(call_types.keys())
    
    # Display call type options
    print("📋 Select call type:")
    print()
    for i, ct_id in enumerate(call_type_ids, 1):
        ct = call_types[ct_id]
        icon = ct.get('icon', '📝')
        name = ct.get('name', ct_id)
        print(f"  {i:2}. {icon} {name}")
    print()
    
    # Get selection
    while True:
        selection = input(f"Enter number (1-{len(call_type_ids)}) or press Enter for generic: ").strip()
        if not selection:
            selected_type = 'generic'
            break
        try:
            idx = int(selection) - 1
            if 0 <= idx < len(call_type_ids):
                selected_type = call_type_ids[idx]
                break
        except ValueError:
            pass
        print("Invalid selection. Please try again.")
    
    call_type = call_types.get(selected_type, {})
    call_type_name = call_type.get('name', 'Recording')
    
    # Check if we need a name input (for 1:1s, customer meetings, etc.)
    person_name = None
    if call_type.get('requires_person_name'):
        print()
        name_prompt = call_type.get('name_prompt', "Enter person's name")
        person_name = input(f"👤 {name_prompt}: ").strip()
        if person_name:
            # Include person name in title
            title = f"{call_type_name} - {person_name}"
        else:
            title = call_type_name
    else:
        # Use call type name as default title, allow override
        print()
        custom_title = input(f"📝 Enter title (or Enter for '{call_type_name}'): ").strip()
        title = custom_title if custom_title else call_type_name
    
    return {
        'title': title,
        'call_type': selected_type,
        'person_name': person_name,
    }


def prompt_for_title() -> str:
    """Prompt user for meeting title (legacy, simple prompt)."""
    print()
    print("=" * 50)
    print("🎙️  WhisperX Recording")
    print("=" * 50)
    print()
    title = input("📝 Enter meeting title (or press Enter for 'Recording'): ").strip()
    return title if title else "Recording"


def begin_recording(
    title: str = None,
    interactive: bool = False,
    diarize: bool = None,
    call_type: str = None,
    person_name: str = None
):
    """
    Start a new recording session.
    
    Args:
        title: Meeting title for the recording
        interactive: If True, prompt for call type and title
        diarize: Enable speaker diarization (default: use saved setting)
        call_type: Call type ID (e.g., 'team_meeting', 'one_on_one')
        person_name: For 1:1s, the person's name
    """
    if is_recording():
        print("ERROR: Recording already in progress", file=sys.stderr)
        return False
    
    # Get diarize setting
    if diarize is None:
        diarize = get_diarize_setting()
    
    # Get recording details
    if interactive and not title:
        details = prompt_for_recording_details()
        title = details['title']
        call_type = details['call_type']
        person_name = details.get('person_name')
    else:
        call_type = call_type or 'generic'
        
        # Check if this call type requires a person name
        call_types = get_call_types()
        call_type_info = call_types.get(call_type, {})
        call_type_name = call_type_info.get('name', 'Recording')
        
        if call_type_info.get('requires_person_name') and not person_name:
            # Prompt for name if not provided (supports custom prompt text)
            print()
            print("=" * 50)
            print(f"🎙️  {call_type_name} Recording")
            print("=" * 50)
            name_prompt = call_type_info.get('name_prompt', "Enter person's name")
            person_name = input(f"👤 {name_prompt}: ").strip()
        
        # Build title
        if not title:
            if person_name:
                title = f"{call_type_name} - {person_name}"
            else:
                title = call_type_name
    
    # Generate paths
    paths = generate_paths(title)
    
    # Create directories
    Path(paths['output_dir']).mkdir(parents=True, exist_ok=True)
    Path(paths['transcript_dir']).mkdir(parents=True, exist_ok=True)
    
    # Launch OBS and start recording. Wrapped broadly (rather than around just
    # one call) because this runs unattended from SwiftBar's terminal=false
    # launches, where a crash has no window to print a traceback into - any
    # exception here must be caught, logged, and surfaced via notification
    # instead of failing silently.
    try:
        # Launch OBS if not running
        if not is_obs_running():
            print("🚀 Launching OBS...")
            launch_obs()
            import time
            time.sleep(5)  # Wait for OBS to start

        # Start recording
        print("▶️  Starting recording...")
        if not start_recording():
            print("ERROR: Failed to send start command to OBS (is it running and reachable?)", file=sys.stderr)
            notify("Recording Failed", "Could not reach OBS to start recording")
            return False

        # Verify OBS actually confirms it's recording, not just that the command
        # was accepted - catches OBS being stuck behind a blocking modal dialog,
        # where `recording start` returns success but no file ever gets written.
        import time
        for _ in range(5):
            time.sleep(1)
            if is_recording_active():
                break
        else:
            print("ERROR: OBS did not confirm recording started. Check OBS for a blocking dialog.", file=sys.stderr)
            notify("Recording Failed", "OBS didn't confirm recording started - check for a blocking dialog")
            return False
    except Exception as e:
        print(f"ERROR: Failed to start recording: {e}", file=sys.stderr)
        logger.error(f"Failed to start recording: {e}")
        logger.error(traceback.format_exc())
        notify("Recording Failed", str(e))
        return False

    # Save state
    state = {
        'recording': True,
        'started_at': datetime.now().isoformat(),
        'title': title,
        'diarize': diarize,
        'call_type': call_type,
        'person_name': person_name,
        'paths': paths
    }
    save_state(state)
    
    # Get call type info for display
    call_type_info = get_call_type(call_type)
    call_type_name = call_type_info.get('name', call_type)
    
    # Write initial metadata
    metadata = {
        'meeting_title': title,
        'call_type': call_type,
        'call_type_name': call_type_name,
        'person_name': person_name,
        'recording_started': state['started_at'],
        'recording_stopped': None,
    }
    with open(paths['metadata_file'], 'w') as f:
        json.dump(metadata, f, indent=2)
    
    print()
    print(f"✅ Recording started: {title}")
    print(f"📁 Output directory: {paths['output_dir']}")
    print(f"📋 Call type: {call_type_name}")
    print(f"🎤 Speaker diarization: {'enabled' if diarize else 'disabled'}")
    if person_name:
        print(f"👤 Person: {person_name}")
    print()
    print("Use the menu bar icon to stop recording.")
    
    # Send notification
    notify("Recording Started", f"{title}")
    
    return True


def end_recording():
    """
    Stop the current recording session and spawn background transcription.

    Best-effort: failures talking to OBS (unreachable websocket, 1Password
    secret unresolvable, etc.) must not block state cleanup and background
    transcription — the mkv OBS already wrote to disk still needs to be
    picked up, and leaving `recording: true` in the state file wedges the
    SwiftBar plugin.
    """
    state = load_state()
    if not state.get('recording'):
        print("ERROR: No recording in progress", file=sys.stderr)
        return False

    # Stop recording (best-effort — OBS may already be gone)
    print("⏹️  Stopping recording...")
    try:
        stop_recording()
    except Exception as e:
        print(f"⚠️  Could not signal OBS to stop (continuing with recovery): {e}", file=sys.stderr)

    # Verify OBS actually confirms the recording stopped before closing it -
    # a blind fixed sleep can race OBS's own finalization, and closing OBS
    # while it still considers itself recording triggers its "still
    # recording, are you sure you want to quit?" confirmation dialog.
    import time
    for _ in range(5):
        if not is_recording_active():
            break
        time.sleep(1)
    else:
        print("⚠️  OBS did not confirm recording stopped in time; closing anyway", file=sys.stderr)

    # Update state
    stopped_at = datetime.now().isoformat()
    paths = state['paths']
    title = state['title']
    diarize = state.get('diarize', get_diarize_setting())

    # Update metadata
    metadata_file = paths['metadata_file']
    if os.path.exists(metadata_file):
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)
        metadata['recording_stopped'] = stopped_at
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

    # Close OBS (best-effort)
    print("🛑 Closing OBS...")
    try:
        close_obs()
    except Exception as e:
        print(f"⚠️  Could not close OBS cleanly: {e}", file=sys.stderr)

    # Clear recording state immediately (allows new recordings)
    clear_state()
    
    # Spawn background processing
    print("🚀 Starting background transcription...")
    spawn_background_processing(state, diarize)
    
    print(f"✅ Recording stopped: {title}")
    print("📝 Transcription running in background - you can start a new recording.")
    notify("Recording Stopped", f"Processing: {title}")
    return True


def spawn_background_processing(state: dict, diarize: bool):
    """Spawn background process to handle transcription."""
    # Build command for background process
    script_path = Path(__file__).resolve()
    
    # Prepare background state (includes call type info)
    bg_state = {
        'paths': state['paths'],
        'title': state['title'],
        'diarize': diarize,
        'call_type': state.get('call_type', 'generic'),
        'person_name': state.get('person_name'),
    }
    
    cmd = [
        sys.executable,
        str(script_path),
        '_process_background',
        json.dumps(bg_state),
    ]
    
    # Spawn detached process
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    
    # Add job to processing queue
    call_type_info = get_call_type(state.get('call_type', 'generic'))
    job = {
        'pid': process.pid,
        'title': state['title'],
        'started_at': datetime.now().isoformat(),
        'diarize': diarize,
        'call_type': state.get('call_type', 'generic'),
        'call_type_name': call_type_info.get('name', 'Recording'),
    }
    add_processing_job(job)


def process_recording(state: dict):
    """Process the recorded video file."""
    paths = state['paths']
    
    # Find the latest video file
    video_files = list(OBS_RECORD_DIR.glob('*.mov')) + \
                  list(OBS_RECORD_DIR.glob('*.mkv')) + \
                  list(OBS_RECORD_DIR.glob('*.mp4'))
    
    if not video_files:
        print("ERROR: No video file found", file=sys.stderr)
        return False
    
    latest = max(video_files, key=lambda p: p.stat().st_mtime)
    
    # Move to output directory
    extension = latest.suffix
    video_file = Path(paths['output_dir']) / f"{paths['filename']}{extension}"
    latest.rename(video_file)
    
    print(f"📁 Moved recording to: {video_file}")
    
    # Extract audio
    print("🎵 Extracting audio...")
    audio_file = paths['audio_file']
    subprocess.run([
        'ffmpeg', '-i', str(video_file),
        '-ar', '16000', '-ac', '1',
        audio_file
    ], capture_output=True)
    
    # Verify and delete video
    if os.path.exists(audio_file) and os.path.getsize(audio_file) > 0:
        print("✅ Audio extraction successful, removing video...")
        video_file.unlink()
    else:
        print("ERROR: Audio extraction failed", file=sys.stderr)
        return False
    
    # Run WhisperX transcription
    diarize = state.get('diarize', get_diarize_setting())
    run_whisperx(audio_file, paths['transcript_dir'], diarize=diarize)
    
    print(f"✅ Transcription complete: {paths['transcript_dir']}")
    return True


def run_whisperx(audio_file: str, output_dir: str, diarize: bool = None):
    """
    Run WhisperX transcription on an audio file.
    
    Args:
        audio_file: Path to the audio file
        output_dir: Directory to save transcript files
        diarize: Enable speaker diarization (default: use saved setting)
    """
    if diarize is None:
        diarize = get_diarize_setting()
    
    print("📝 Starting transcription (this may take a while)...")
    if diarize:
        print("   Speaker diarization: enabled")
    else:
        print("   Speaker diarization: disabled (faster)")
    print()
    
    os.environ['TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD'] = '1'
    # Multiple native libs (torch, ctranslate2, scipy) each bundle their own OpenMP runtime on
    # Intel macOS; without these, concurrent init reliably segfaults or deadlocks mid-transcription.
    os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'
    os.environ['OMP_NUM_THREADS'] = '1'

    cmd = [
        str(WHISPERX_PATH), audio_file,
        '--language', 'en',
        '--compute_type', 'float32',
        '--device', 'cpu',
        '--output_dir', output_dir,
    ]
    
    if diarize:
        cmd.extend(['--diarize', '--hf_token', resolve_secret(HF_TOKEN)])
    
    subprocess.run(cmd)


# ─── LLM Analysis ─────────────────────────────────────────────────

def load_transcript(transcript_dir: str) -> Optional[str]:
    """
    Load the transcript text from the output directory.
    Prefers .txt file, falls back to .json if needed.
    """
    logger.debug(f"Loading transcript from: {transcript_dir}")
    transcript_path = Path(transcript_dir)
    
    if not transcript_path.exists():
        logger.error(f"Transcript directory does not exist: {transcript_dir}")
        return None
    
    # List all files in directory for debugging
    all_files = list(transcript_path.glob('*'))
    logger.debug(f"Files in transcript dir: {[f.name for f in all_files]}")
    
    # Try .txt file first (WhisperX outputs this)
    txt_files = list(transcript_path.glob('*.txt'))
    logger.debug(f"Found {len(txt_files)} .txt files")
    if txt_files:
        logger.info(f"Loading transcript from: {txt_files[0]}")
        with open(txt_files[0], 'r', encoding='utf-8') as f:
            content = f.read()
            logger.debug(f"Loaded {len(content)} chars from .txt file")
            return content
    
    # Fall back to .json with word-level data
    json_files = list(transcript_path.glob('*.json'))
    logger.debug(f"Found {len(json_files)} .json files")
    if json_files:
        logger.info(f"Loading transcript from JSON: {json_files[0]}")
        with open(json_files[0], 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Extract text from segments
            if 'segments' in data:
                lines = []
                for seg in data['segments']:
                    speaker = seg.get('speaker', '')
                    text = seg.get('text', '').strip()
                    if speaker:
                        lines.append(f"[{speaker}]: {text}")
                    else:
                        lines.append(text)
                content = '\n'.join(lines)
                logger.debug(f"Extracted {len(content)} chars from JSON segments")
                return content
            else:
                logger.warning("JSON file has no 'segments' key")
    
    logger.warning("No transcript files found")
    return None


def analyze_with_llm(
    transcript: str,
    call_type_id: str,
    person_name: Optional[str] = None,
    output_dir: str = None,
    title: str = None
) -> Optional[str]:
    """
    Send transcript to the configured LLM provider (OpenAI or Anthropic) for analysis.

    Args:
        transcript: The transcript text to analyze
        call_type_id: ID of the call type (e.g., 'team_meeting', 'one_on_one')
        person_name: For 1:1s, the person's name to include in prompt
        output_dir: Directory to save the analysis output
        title: Recording title for context

    Returns:
        The analysis text, or None if failed
    """
    logger.info(f"Starting LLM analysis for: {title}")
    logger.debug(f"Call type: {call_type_id}, Person: {person_name}")

    if not is_llm_enabled():
        logger.warning("LLM analysis not configured - skipping analysis")
        print("⚠️  LLM analysis not configured - skipping analysis")
        return None

    llm_config = get_llm_config()
    call_type = get_call_type(call_type_id)

    logger.debug(f"LLM config: provider={llm_config.get('provider')}, enabled={llm_config.get('enabled')}")
    
    # Load context files if specified
    context = ""
    if 'context_files' in call_type:
        context = load_context_files(call_type['context_files'])
        if context:
            logger.info(f"Loaded context for call type '{call_type_id}'")
            print(f"📚 Loaded {len(call_type['context_files'])} context file(s)")
    
    # Get the prompt - supports external file, template, or inline prompt
    prompt = ''
    
    # Try loading from external prompt file first
    if call_type.get('prompt_file'):
        prompt_file_path = call_type['prompt_file']
        base_path = Path(_config.get('context_base_path', SCRIPT_DIR.parent))
        full_path = base_path / prompt_file_path
        
        if full_path.exists():
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    prompt = f.read()
                logger.info(f"Loaded prompt from file: {prompt_file_path}")
            except Exception as e:
                logger.warning(f"Failed to load prompt file {prompt_file_path}: {e}")
        else:
            logger.warning(f"Prompt file not found: {full_path}")
    
    # Fall back to inline prompt or template
    if not prompt:
        if call_type.get('requires_person_name') and person_name:
            prompt = call_type.get('prompt_template', '')
        else:
            prompt = call_type.get('prompt', '')
    
    # Substitute person_name if present in prompt (works for both file and inline)
    if person_name and '{person_name}' in prompt:
        prompt = prompt.format(person_name=person_name)
    
    if not prompt:
        logger.warning(f"No prompt configured for call type '{call_type_id}' - using generic")
        print("⚠️  No prompt configured for call type - using generic")
        call_type = get_call_type('generic')
        prompt = call_type.get('prompt', 'Please summarize this transcript.')
    
    logger.debug(f"Prompt length: {len(prompt)} chars")
    
    # Combine context and prompt into system message
    if context:
        system_message = f"{context}\n\n---\n\n{prompt}"
        logger.debug(f"Combined context + prompt: {len(system_message)} chars")
    else:
        system_message = prompt
    
    user_message = f"## Meeting: {title}\n\n## Transcript:\n\n{transcript}"
    
    # Determine provider and model
    provider = llm_config.get('provider', 'openai')
    if provider == 'anthropic':
        model = llm_config.get('anthropic_model', 'claude-sonnet-5')
    else:
        model = llm_config.get('model', 'gpt-4o')

    logger.info(f"Sending to LLM: provider={provider}, model={model}, transcript_len={len(transcript)}")
    print(f"🤖 Analyzing transcript with {provider}...")
    print(f"   Model: {model}")
    print(f"   Call type: {call_type.get('name', call_type_id)}")
    if person_name:
        print(f"   Person: {person_name}")
    print()

    try:
        if provider == 'anthropic':
            import anthropic
            logger.debug("Creating Anthropic client...")
            client = anthropic.Anthropic(api_key=resolve_secret(llm_config['anthropic_api_key']))

            logger.info("Calling Anthropic API...")
            response = client.messages.create(
                model=model,
                max_tokens=4000,
                system=system_message,
                messages=[{"role": "user", "content": user_message}],
            )
            logger.info("Anthropic API call successful")

            analysis = next((b.text for b in response.content if b.type == "text"), None)
            if analysis is None:
                logger.error(f"Anthropic returned no text content (stop_reason={response.stop_reason})")
                print(f"❌ Anthropic returned no text (stop_reason: {response.stop_reason})", file=sys.stderr)
                return None
        else:
            import openai
            logger.debug(f"OpenAI library version: {openai.__version__}")
            logger.debug("Creating direct OpenAI client...")
            client = openai.OpenAI(api_key=resolve_secret(llm_config['api_key']))

            api_params = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message}
                ],
                "temperature": 0.3,  # Lower temperature for more consistent analysis
            }

            # Use max_completion_tokens for newer models (o1, gpt-5, etc.)
            if model.startswith(('o1', 'gpt-5', 'gpt-4o-')):
                api_params["max_completion_tokens"] = 4000
            else:
                api_params["max_tokens"] = 4000

            logger.info("Calling OpenAI API...")
            response = client.chat.completions.create(**api_params)
            logger.info("OpenAI API call successful")

            analysis = response.choices[0].message.content

        logger.info(f"LLM response received: {len(analysis)} chars")
        logger.debug(f"Response preview: {analysis[:200]}...")
        
        # Save analysis to file with timestamp and model name for comparison
        if output_dir:
            output_path = Path(output_dir)
            timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
            safe_model = model.replace('/', '-').replace(':', '-')  # Sanitize for filename
            analysis_file = output_path / f"analysis_{timestamp}_{safe_model}.md"
            
            # Build the full output with metadata
            full_output = f"""# {call_type.get('name', 'Meeting')} Analysis

**Title:** {title}
**Call Type:** {call_type.get('name', call_type_id)}
**Analyzed:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Provider:** {provider}
**Model:** {model}
"""
            if person_name:
                full_output += f"**Person:** {person_name}\n"
            
            full_output += f"""
---

{analysis}
"""
            
            logger.debug(f"Writing analysis to: {analysis_file}")
            with open(analysis_file, 'w', encoding='utf-8') as f:
                f.write(full_output)
            
            logger.info(f"Analysis saved successfully: {analysis_file}")
            print(f"✅ Analysis saved: {analysis_file}")
            
            # Upload to Google Drive if enabled
            if is_gdrive_enabled():
                print("📤 Uploading to Google Drive...")
                gdrive_url = upload_to_gdrive(
                    analysis_file=analysis_file,
                    call_type_name=call_type.get('name', 'Analysis'),
                    title=title,
                    analyzed_date=datetime.now()
                )
                if gdrive_url:
                    print(f"✅ Google Doc: {gdrive_url}")
                else:
                    print("⚠️  Google Drive upload failed (see logs)")
        
        return analysis
        
    except ImportError as e:
        logger.error(f"LLM package not installed: {e}")
        logger.error(traceback.format_exc())
        pkg = "anthropic" if provider == 'anthropic' else "openai"
        print(f"❌ {pkg} package not installed. Run: pip install {pkg}", file=sys.stderr)
        return None
    except Exception as e:
        logger.error(f"LLM analysis failed: {e}")
        logger.error(traceback.format_exc())
        print(f"❌ LLM analysis failed: {e}", file=sys.stderr)
        return None


# ─── Process Existing Video ──────────────────────────────────────────────────

def process_existing_video(
    video_path: str,
    title: str = None,
    keep_video: bool = None,
    diarize: bool = None,
    call_type: str = None,
    person_name: str = None
):
    """
    Process an existing video file - extract audio, transcribe, and analyze.

    Args:
        video_path: Path to the video file
        title: Optional title for the recording (derived from filename if not provided)
        keep_video: If True, don't delete the original video after processing (default: use saved setting)
        diarize: Enable speaker diarization (default: use saved setting)
        call_type: Call type ID for LLM analysis
        person_name: Person name for 1:1 meetings
    """
    if keep_video is None:
        keep_video = get_keep_video_setting()

    video_file = Path(video_path).resolve()

    if not video_file.exists():
        print(f"ERROR: Video file not found: {video_file}", file=sys.stderr)
        return False
    
    if video_file.suffix.lower() not in ['.mov', '.mkv', '.mp4', '.avi', '.webm']:
        print(f"ERROR: Unsupported video format: {video_file.suffix}", file=sys.stderr)
        return False
    
    # Determine title from filename if not provided
    if not title:
        # Try to extract title from filename (remove extension and common prefixes)
        title = video_file.stem
        # Remove date/time patterns like "2026-01-06 12-30-45" or "20260106_123045"
        title = re.sub(r'^\d{4}[-_]?\d{2}[-_]?\d{2}[-_\s]*\d{2}[-_]?\d{2}[-_]?\d{2}[-_\s]*', '', title)
        title = re.sub(r'^\d{8}[-_\s]*\d{6}[-_\s]*', '', title)
        if not title:
            title = "Recording"
    
    # Default call type
    call_type = call_type or 'generic'
    call_type_info = get_call_type(call_type)
    call_type_name = call_type_info.get('name', call_type)
    
    print()
    print("=" * 60)
    print("🎬 Processing Existing Video")
    print("=" * 60)
    print()
    print(f"📁 Input: {video_file}")
    print(f"📝 Title: {title}")
    print(f"📋 Call type: {call_type_name}")
    if person_name:
        print(f"👤 Person: {person_name}")
    print()
    
    # Generate output paths
    paths = generate_paths(title)
    
    # Create directories
    Path(paths['output_dir']).mkdir(parents=True, exist_ok=True)
    Path(paths['transcript_dir']).mkdir(parents=True, exist_ok=True)
    
    # Get file modification time for metadata
    file_mtime = datetime.fromtimestamp(video_file.stat().st_mtime)
    
    # Write metadata
    metadata = {
        'meeting_title': title,
        'call_type': call_type,
        'call_type_name': call_type_name,
        'person_name': person_name,
        'original_file': str(video_file),
        'file_date': file_mtime.isoformat(),
        'processed_at': datetime.now().isoformat(),
    }
    with open(paths['metadata_file'], 'w') as f:
        json.dump(metadata, f, indent=2)
    
    # Extract audio
    print("🎵 Extracting audio...")
    audio_file = paths['audio_file']
    result = subprocess.run([
        'ffmpeg', '-i', str(video_file),
        '-ar', '16000', '-ac', '1',
        '-y',  # Overwrite output file if exists
        audio_file
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"ERROR: ffmpeg failed: {result.stderr}", file=sys.stderr)
        return False
    
    # Verify audio extraction
    if not os.path.exists(audio_file) or os.path.getsize(audio_file) == 0:
        print("ERROR: Audio extraction failed - empty output", file=sys.stderr)
        return False
    
    print(f"✅ Audio extracted: {audio_file}")
    
    # Optionally delete original video
    if not keep_video:
        print("🗑️  Removing original video...")
        video_file.unlink()
    
    # Run WhisperX transcription
    print()
    run_whisperx(audio_file, paths['transcript_dir'], diarize=diarize)
    
    # Run LLM analysis if auto-analyze is enabled (transcript is the default deliverable;
    # run `analyze <folder>` manually otherwise)
    if should_auto_analyze():
        print()
        transcript = load_transcript(paths['transcript_dir'])
        if transcript:
            analyze_with_llm(
                transcript=transcript,
                call_type_id=call_type,
                person_name=person_name,
                output_dir=paths['output_dir'],
                title=title
            )

    print()
    print("=" * 60)
    print(f"✅ Processing complete!")
    print(f"📁 Output directory: {paths['output_dir']}")
    print(f"📝 Transcript: {paths['transcript_dir']}")
    if should_auto_analyze():
        print(f"🤖 Analysis: {paths['output_dir']}/analysis_*.md")
    elif is_llm_enabled():
        print(f"💡 Run analysis manually: whisperx-recorder analyze {paths['output_dir']}")
    print("=" * 60)
    return True


# ─── Status Information ───────────────────────────────────────────────────────

def get_status() -> dict:
    """Get current recording and processing status."""
    state = load_state()
    recording = state.get('recording', False)
    processing_jobs = load_processing_jobs()
    
    result = {
        'recording': recording,
        'processing': len(processing_jobs) > 0,
        'processing_count': len(processing_jobs),
        'processing_jobs': processing_jobs,
        'obs_running': is_obs_running(),
    }
    
    if recording:
        result['title'] = state.get('title', 'Unknown')
        result['started_at'] = state.get('started_at')
    
    return result


def run_background_processing(bg_state_json: str):
    """
    Internal function called by background process to do actual transcription
    and LLM analysis.
    This runs in a separate process spawned by end_recording.
    """
    # Re-initialize logging for background process
    setup_logging()
    
    logger.info("=" * 60)
    logger.info("BACKGROUND PROCESSING STARTED")
    logger.info("=" * 60)
    
    bg_state = json.loads(bg_state_json)
    paths = bg_state['paths']
    title = bg_state['title']
    diarize = bg_state.get('diarize', True)
    call_type = bg_state.get('call_type', 'generic')
    person_name = bg_state.get('person_name')
    my_pid = os.getpid()
    
    logger.info(f"Processing: {title}")
    logger.info(f"PID: {my_pid}")
    logger.info(f"Call type: {call_type}")
    logger.info(f"Diarize: {diarize}")
    logger.info(f"Output dir: {paths['output_dir']}")
    
    try:
        # Find the latest video file
        logger.debug(f"Looking for video files in: {OBS_RECORD_DIR}")
        video_files = list(OBS_RECORD_DIR.glob('*.mov')) + \
                      list(OBS_RECORD_DIR.glob('*.mkv')) + \
                      list(OBS_RECORD_DIR.glob('*.mp4'))
        
        logger.debug(f"Found {len(video_files)} video files")
        
        if not video_files:
            logger.error("No video file found!")
            notify("Processing Error", f"No video file found for: {title}")
            return False
        
        latest = max(video_files, key=lambda p: p.stat().st_mtime)
        logger.info(f"Processing video: {latest}")
        
        # Move to output directory
        extension = latest.suffix
        video_file = Path(paths['output_dir']) / f"{paths['filename']}{extension}"
        logger.debug(f"Moving to: {video_file}")
        latest.rename(video_file)
        
        # Extract audio
        audio_file = paths['audio_file']
        logger.info(f"Extracting audio to: {audio_file}")
        result = subprocess.run([
            'ffmpeg', '-i', str(video_file),
            '-ar', '16000', '-ac', '1',
            audio_file
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"ffmpeg failed: {result.stderr}")
        
        # Verify and delete video
        if os.path.exists(audio_file) and os.path.getsize(audio_file) > 0:
            logger.info(f"Audio extraction successful, size: {os.path.getsize(audio_file)} bytes")
            if not get_keep_video_setting():
                video_file.unlink()
                logger.debug("Video file deleted")
            else:
                logger.info("keep_video enabled - preserving source video")
        else:
            logger.error(f"Audio extraction failed - file missing or empty")
            notify("Processing Error", f"Audio extraction failed for: {title}")
            return False
        
        # Run WhisperX transcription
        logger.info("Starting WhisperX transcription...")
        run_whisperx(audio_file, paths['transcript_dir'], diarize=diarize)
        logger.info("WhisperX transcription complete")
        
        # Run LLM analysis if auto-analyze is enabled (transcript is the default deliverable)
        logger.info(f"Checking auto-analyze status: {should_auto_analyze()}")
        if should_auto_analyze():
            logger.info("Auto-analyze enabled, loading transcript...")
            transcript = load_transcript(paths['transcript_dir'])
            if transcript:
                logger.info(f"Transcript loaded: {len(transcript)} chars")
                logger.debug(f"Transcript preview: {transcript[:200]}...")
                
                analysis = analyze_with_llm(
                    transcript=transcript,
                    call_type_id=call_type,
                    person_name=person_name,
                    output_dir=paths['output_dir'],
                    title=title
                )
                
                if analysis:
                    logger.info("LLM analysis completed successfully")
                    notify("Analysis Complete", f"Finished: {title}")
                else:
                    logger.warning("LLM analysis returned None")
                    notify("Transcription Complete", f"Finished: {title} (analysis failed)")
            else:
                logger.warning("No transcript found for analysis")
                notify("Transcription Complete", f"Finished: {title} (no transcript for analysis)")
        else:
            logger.info("Auto-analyze not enabled, skipping analysis")
            # Success notification
            notify("Transcription Complete", f"Finished: {title}")
        
        logger.info("=" * 60)
        logger.info("BACKGROUND PROCESSING COMPLETE")
        logger.info("=" * 60)
        return True
        
    except Exception as e:
        logger.error(f"Background processing failed: {e}")
        logger.error(traceback.format_exc())
        notify("Processing Error", f"Failed: {title}")
        return False
        
    finally:
        # Remove only this job from the queue
        logger.debug(f"Removing job from queue: PID {my_pid}")
        remove_processing_job(my_pid)


# ─── CLI Interface ────────────────────────────────────────────────────────────

def parse_args(args: list) -> tuple:
    """Parse command line arguments, extracting flags."""
    flags = {}
    remaining = []
    i = 0
    
    while i < len(args):
        arg = args[i]
        if arg == '--no-diarize':
            flags['diarize'] = False
        elif arg == '--diarize':
            flags['diarize'] = True
        elif arg == '--keep-video':
            flags['keep_video'] = True
        elif arg == '--delete-video':
            flags['keep_video'] = False
        elif arg == '--call-type' and i + 1 < len(args):
            flags['call_type'] = args[i + 1]
            i += 1
        elif arg == '--person' and i + 1 < len(args):
            flags['person_name'] = args[i + 1]
            i += 1
        elif arg.startswith('--call-type='):
            flags['call_type'] = arg.split('=', 1)[1]
        elif arg.startswith('--person='):
            flags['person_name'] = arg.split('=', 1)[1]
        elif arg == '--days' and i + 1 < len(args):
            flags['days'] = args[i + 1]
            i += 1
        elif arg.startswith('--days='):
            flags['days'] = arg.split('=', 1)[1]
        else:
            remaining.append(arg)
        i += 1
    
    return remaining, flags


def main():
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        diarize_status = "enabled" if get_diarize_setting() else "disabled"
        llm_status = "configured, auto-run " + ("on" if should_auto_analyze() else "off") if is_llm_enabled() else "not configured"
        
        print("Usage: whisperx_recorder.py <command> [args] [flags]")
        print()
        print("Commands:")
        print("  start [title]           - Start recording (prompts if not provided)")
        print("  stop                    - Stop recording and transcribe")
        print("  process <video> [title] - Process existing video file")
        print("  analyze <folder>        - Run LLM analysis on existing transcript")
        print("  gdrive-upload [folder]  - Upload analysis files to Google Drive")
        print("  config diarize <on|off> - Set default diarization preference")
        print("  types                   - List available call types")
        print("  status                  - Get current status (JSON output)")
        print("  logs [N]                - Show last N log entries (default: 50)")
        print("  logs-clear              - Clear all logs")
        print()
        print("Flags:")
        print("  --no-diarize            - Skip speaker diarization (faster, offline)")
        print("  --diarize               - Enable speaker diarization")
        print("  --keep-video            - Preserve the source video after processing (process command)")
        print("  --delete-video          - Delete the source video after processing (process command)")
        print("  --call-type <type>      - Specify call type (e.g., team_meeting)")
        print("  --person <name>         - Person name (for 1:1 meetings)")
        print("  --days <N>              - Days to look back for gdrive-upload (default: 3)")
        print()
        print(f"Current diarization default: {diarize_status}")
        print(f"LLM analysis: {llm_status}")
        print(f"Log file: {LOG_FILE}")
        print()
        print("Examples:")
        print("  whisperx_recorder.py start                      # Interactive mode")
        print("  whisperx_recorder.py start 'Weekly Sync' --call-type team_meeting")
        print("  whisperx_recorder.py start '1:1 - John' --call-type one_on_one --person John")
        print("  whisperx_recorder.py process ~/video.mov --call-type interview_sa")
        print("  whisperx_recorder.py logs 100                   # Show last 100 log entries")
        sys.exit(1)
    
    # Parse arguments
    args, flags = parse_args(sys.argv[1:])
    command = args[0].lower() if args else ''
    
    if command == 'start':
        title = ' '.join(args[1:]) if len(args) > 1 else None
        diarize = flags.get('diarize', get_diarize_setting())
        call_type = flags.get('call_type')
        person_name = flags.get('person_name')
        
        # If no title and no call_type, go interactive
        interactive = (title is None and call_type is None)
        
        success = begin_recording(
            title=title,
            interactive=interactive,
            diarize=diarize,
            call_type=call_type,
            person_name=person_name
        )
        sys.exit(0 if success else 1)
    
    elif command == 'types':
        # List available call types
        call_types = get_call_types()
        print()
        print("Available Call Types:")
        print("=" * 50)
        for ct_id, ct in call_types.items():
            icon = ct.get('icon', '📝')
            name = ct.get('name', ct_id)
            requires_person = "👤" if ct.get('requires_person_name') else ""
            print(f"  {icon} {ct_id:20} - {name} {requires_person}")
        print()
        print("Use with: --call-type <type_id>")
        print("👤 = requires --person flag")
        sys.exit(0)
    
    elif command == 'stop':
        success = end_recording()
        sys.exit(0 if success else 1)
    
    elif command == 'process':
        if len(args) < 2:
            print("ERROR: Video file path required", file=sys.stderr)
            print("Usage: whisperx_recorder.py process <video_path> [title] [flags]", file=sys.stderr)
            print("Flags: --call-type <type>, --person <name>, --no-diarize, --keep-video/--delete-video", file=sys.stderr)
            sys.exit(1)

        video_path = args[1]
        title = ' '.join(args[2:]) if len(args) > 2 else None
        diarize = flags.get('diarize', get_diarize_setting())
        keep_video = flags.get('keep_video', get_keep_video_setting())
        call_type = flags.get('call_type')
        person_name = flags.get('person_name')
        success = process_existing_video(
            video_path, title,
            keep_video=keep_video,
            diarize=diarize,
            call_type=call_type,
            person_name=person_name
        )
        sys.exit(0 if success else 1)
    
    elif command == 'config':
        if len(args) < 3:
            print("Usage: whisperx_recorder.py config diarize <on|off>", file=sys.stderr)
            sys.exit(1)
        
        setting = args[1].lower()
        value = args[2].lower()
        
        if setting == 'diarize':
            if value in ('on', 'true', '1', 'yes', 'enabled'):
                set_diarize_setting(True)
            elif value in ('off', 'false', '0', 'no', 'disabled'):
                set_diarize_setting(False)
            else:
                print(f"Invalid value: {value}. Use 'on' or 'off'", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"Unknown setting: {setting}", file=sys.stderr)
            sys.exit(1)
    
    elif command == 'status':
        status = get_status()
        status['diarize_default'] = get_diarize_setting()
        status['llm_enabled'] = is_llm_enabled()
        status['log_file'] = str(LOG_FILE)
        print(json.dumps(status, indent=2))
    
    elif command == 'logs':
        # Show recent logs
        lines = 50  # default
        if len(args) > 1:
            try:
                lines = int(args[1])
            except ValueError:
                pass
        
        if LOG_FILE.exists():
            with open(LOG_FILE, 'r') as f:
                all_lines = f.readlines()
                recent = all_lines[-lines:] if len(all_lines) > lines else all_lines
                print(f"📋 Last {len(recent)} log entries from {LOG_FILE}:\n")
                print("".join(recent))
        else:
            print(f"No log file found at {LOG_FILE}")
    
    elif command == 'logs-clear':
        # Clear logs
        if LOG_FILE.exists():
            LOG_FILE.unlink()
            print(f"✅ Logs cleared: {LOG_FILE}")
        else:
            print("No logs to clear")
    
    elif command == 'analyze':
        # Manually run LLM analysis on existing transcript
        if len(args) < 2:
            print("ERROR: Recording folder path required", file=sys.stderr)
            print("Usage: whisperx_recorder.py analyze <recording_folder> [--call-type <type>]", file=sys.stderr)
            print("Example: whisperx_recorder.py analyze ~/OBSRecordings/2026-01-16_Recording", file=sys.stderr)
            sys.exit(1)
        
        recording_path = Path(args[1]).expanduser().resolve()
        if not recording_path.exists():
            print(f"ERROR: Path not found: {recording_path}", file=sys.stderr)
            sys.exit(1)
        
        # Find transcript directory
        transcript_dirs = list(recording_path.glob('*_transcript'))
        if not transcript_dirs:
            print(f"ERROR: No transcript directory found in {recording_path}", file=sys.stderr)
            sys.exit(1)
        
        transcript_dir = transcript_dirs[0]
        
        # Load metadata for title
        metadata_files = list(recording_path.glob('*_metadata.json'))
        title = "Recording"
        if metadata_files:
            with open(metadata_files[0], 'r') as f:
                metadata = json.load(f)
                title = metadata.get('meeting_title', 'Recording')
        
        call_type = flags.get('call_type', 'generic')
        person_name = flags.get('person_name')
        
        print()
        print(f"📋 Running LLM analysis on: {recording_path.name}")
        print(f"   Title: {title}")
        print(f"   Call type: {call_type}")
        print()
        
        # Load transcript
        transcript = load_transcript(str(transcript_dir))
        if not transcript:
            print("ERROR: Could not load transcript", file=sys.stderr)
            sys.exit(1)
        
        print(f"📝 Transcript loaded: {len(transcript)} characters")
        print()
        
        # Run analysis
        analysis = analyze_with_llm(
            transcript=transcript,
            call_type_id=call_type,
            person_name=person_name,
            output_dir=str(recording_path),
            title=title
        )
        
        if analysis:
            print()
            print("✅ Analysis complete!")
            sys.exit(0)
        else:
            print()
            print("❌ Analysis failed - check logs with: whisperx-recorder logs")
            sys.exit(1)
    
    elif command == 'gdrive-upload':
        # Upload analysis files to Google Drive
        if not is_gdrive_enabled():
            print("❌ Google Drive is not enabled in configuration", file=sys.stderr)
            print("   Set gdrive.enabled = true in config", file=sys.stderr)
            sys.exit(1)
        
        # Get recording folders to process
        recording_paths = []
        
        if len(args) > 1:
            # Specific path(s) provided
            for arg in args[1:]:
                if arg.startswith('--'):
                    continue
                path = Path(arg).expanduser().resolve()
                if path.is_dir():
                    recording_paths.append(path)
                else:
                    print(f"⚠️  Skipping (not a directory): {arg}", file=sys.stderr)
        else:
            # Find recent recordings with analysis files
            output_dir = OBS_RECORD_DIR
            days = int(flags.get('days', 3))
            print(f"📁 Scanning {output_dir} for analyses from the past {days} days...")
            
            from datetime import timedelta
            cutoff = datetime.now() - timedelta(days=days)
            
            for folder in output_dir.iterdir():
                if not folder.is_dir():
                    continue
                # Check for analysis files
                analysis_files = list(folder.glob('analysis_*.md'))
                if analysis_files:
                    # Check modification time
                    latest = max(f.stat().st_mtime for f in analysis_files)
                    if datetime.fromtimestamp(latest) > cutoff:
                        recording_paths.append(folder)
        
        if not recording_paths:
            print("No recordings with analyses found")
            sys.exit(0)
        
        print(f"\n📤 Found {len(recording_paths)} recording(s) to check\n")
        
        uploaded = 0
        skipped = 0
        failed = 0
        
        for recording_path in sorted(recording_paths):
            # Find analysis files
            analysis_files = list(recording_path.glob('analysis_*.md'))
            if not analysis_files:
                continue
            
            # Load metadata
            metadata_files = list(recording_path.glob('*_metadata.json'))
            if not metadata_files:
                print(f"⚠️  No metadata in {recording_path.name}, skipping")
                skipped += 1
                continue
            
            with open(metadata_files[0], 'r') as f:
                metadata = json.load(f)
            
            call_type_name = metadata.get('call_type_name', 'Recording')
            person_name = metadata.get('person_name')
            meeting_title = metadata.get('meeting_title', recording_path.name)
            
            # Use person_name as title for 1:1s, otherwise meeting_title
            title = person_name if person_name else meeting_title
            
            for analysis_file in analysis_files:
                # Extract date from filename: analysis_YYYY-MM-DD_HHMMSS_model.md
                filename = analysis_file.name
                try:
                    date_part = filename.split('_')[1]  # YYYY-MM-DD
                    time_part = filename.split('_')[2]  # HHMMSS
                    analyzed_date = datetime.strptime(f"{date_part}_{time_part}", "%Y-%m-%d_%H%M%S")
                except (IndexError, ValueError):
                    analyzed_date = datetime.fromtimestamp(analysis_file.stat().st_mtime)
                
                print(f"📄 {recording_path.name}/{analysis_file.name}")
                print(f"   Call type: {call_type_name}")
                print(f"   Title: {title}")
                
                url = upload_to_gdrive(
                    analysis_file=analysis_file,
                    call_type_name=call_type_name,
                    title=title,
                    analyzed_date=analyzed_date
                )
                
                if url:
                    print(f"   ✅ {url}")
                    uploaded += 1
                else:
                    print(f"   ❌ Upload failed")
                    failed += 1
                print()
        
        print(f"📊 Summary: {uploaded} uploaded, {skipped} skipped, {failed} failed")
        sys.exit(0 if failed == 0 else 1)
    
    elif command == '_process_background':
        # Internal command - called by spawn_background_processing
        if len(args) < 2:
            sys.exit(1)
        bg_state_json = args[1]
        success = run_background_processing(bg_state_json)
        sys.exit(0 if success else 1)
    
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
