#!/Users/smitty.weygant/anaconda3/envs/whisperx-recorder/bin/python
"""
WhisperX Recording Controller

This script handles:
- OBS recording control via obs-cmd
- Meeting title input and file organization
- Metadata generation
- Audio extraction and WhisperX transcription
- OpenAI ChatGPT analysis of transcripts

Configuration:
- Defaults: processing-pipeline/config.default.json (version controlled)
- User overrides: ~/.config/whisperx/settings.json (personal settings)
"""

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
            "obs_ws_password": ""
        },
        "transcription": {
            "diarize": True,
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
    return _config['transcription'].get('diarize', True)


# ─── OpenAI Config Accessors ──────────────────────────────────────────────────

def get_openai_config() -> dict:
    """Get OpenAI configuration."""
    return _config.get('openai', {})


def get_openai_provider() -> str:
    """Get configured OpenAI provider ('openai' or 'databricks')."""
    return get_openai_config().get('provider', 'openai')


def is_openai_enabled() -> bool:
    """Check if OpenAI integration is enabled and properly configured."""
    openai_config = get_openai_config()
    if not openai_config.get('enabled', False):
        return False
    
    provider = openai_config.get('provider', 'openai')
    if provider == 'databricks':
        # Databricks requires a profile (token fetched at runtime)
        return bool(openai_config.get('databricks_profile'))
    else:
        # Direct OpenAI requires an API key
        return bool(openai_config.get('api_key'))


def get_databricks_openai_client(profile: str):
    """
    Create OpenAI client configured for Databricks model serving.
    Uses Databricks SDK to fetch OAuth token from configured profile.
    
    Args:
        profile: Databricks CLI profile name (from ~/.databrickscfg)
    
    Returns:
        tuple: (openai.OpenAI client, host) on success, or (None, error_message) on failure
    """
    try:
        from databricks.sdk import WorkspaceClient
        import openai
        
        logger.debug(f"Connecting to Databricks with profile: {profile}")
        w = WorkspaceClient(profile=profile)
        
        # Get OAuth token and host from SDK
        token = w.config.oauth_token()
        host = w.config.host
        
        logger.debug(f"Databricks host: {host}")
        logger.debug(f"Token obtained: {bool(token)}")
        
        # Create OpenAI client with Databricks endpoint
        client = openai.OpenAI(
            api_key=token.access_token,
            base_url=f"{host}/serving-endpoints"
        )
        
        logger.info(f"Databricks OpenAI client created for {host}")
        return client, host
        
    except ImportError as e:
        logger.error(f"Databricks SDK not installed: {e}")
        return None, "databricks-sdk not installed. Run: pip install databricks-sdk"
    except Exception as e:
        logger.error(f"Databricks connection failed: {e}")
        logger.error(traceback.format_exc())
        return None, str(e)


def get_call_types() -> dict:
    """Get all configured call types."""
    return _config.get('call_types', {})


def get_call_type(call_type_id: str) -> dict:
    """Get a specific call type configuration."""
    call_types = get_call_types()
    return call_types.get(call_type_id, call_types.get('generic', {}))


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
        return f"--websocket obsws://127.0.0.1:{OBS_WS_PORT}/{OBS_WS_PASSWORD}"
    return f"-w ws://127.0.0.1:{OBS_WS_PORT}"


def is_obs_running():
    """Check if OBS is currently running."""
    result = subprocess.run(['pgrep', '-x', 'obs'], capture_output=True)
    return result.returncode == 0


def launch_obs():
    """Launch OBS application."""
    subprocess.run(['open', '-a', 'OBS'])


def start_recording():
    """Start OBS recording."""
    args = get_obs_cmd_args().split()
    subprocess.run(['obs-cmd'] + args + ['recording', 'start'])


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
    
    # Check if we need person name (for 1:1s)
    person_name = None
    if call_type.get('requires_person_name'):
        print()
        person_name = input("👤 Enter person's name: ").strip()
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
            # Prompt for person name if not provided
            print()
            print("=" * 50)
            print(f"🎙️  {call_type_name} Recording")
            print("=" * 50)
            person_name = input("👤 Enter person's name: ").strip()
        
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
    
    # Launch OBS if not running
    if not is_obs_running():
        print("🚀 Launching OBS...")
        launch_obs()
        import time
        time.sleep(5)  # Wait for OBS to start
    
    # Start recording
    print("▶️  Starting recording...")
    start_recording()
    
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
    """
    state = load_state()
    if not state.get('recording'):
        print("ERROR: No recording in progress", file=sys.stderr)
        return False
    
    # Stop recording
    print("⏹️  Stopping recording...")
    stop_recording()
    
    import time
    time.sleep(2)  # Give OBS time to finalize
    
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
    
    # Close OBS
    print("🛑 Closing OBS...")
    close_obs()
    
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
    
    cmd = [
        str(WHISPERX_PATH), audio_file,
        '--language', 'en',
        '--compute_type', 'float32',
        '--device', 'cpu',
        '--output_dir', output_dir,
    ]
    
    if diarize:
        cmd.extend(['--diarize', '--hf_token', HF_TOKEN])
    
    subprocess.run(cmd)


# ─── OpenAI ChatGPT Analysis ─────────────────────────────────────────────────

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


def analyze_with_chatgpt(
    transcript: str,
    call_type_id: str,
    person_name: Optional[str] = None,
    output_dir: str = None,
    title: str = None
) -> Optional[str]:
    """
    Send transcript to ChatGPT for analysis.
    
    Args:
        transcript: The transcript text to analyze
        call_type_id: ID of the call type (e.g., 'team_meeting', 'one_on_one')
        person_name: For 1:1s, the person's name to include in prompt
        output_dir: Directory to save the analysis output
        title: Recording title for context
    
    Returns:
        The analysis text, or None if failed
    """
    logger.info(f"Starting ChatGPT analysis for: {title}")
    logger.debug(f"Call type: {call_type_id}, Person: {person_name}")
    
    if not is_openai_enabled():
        logger.warning("OpenAI not configured - skipping analysis")
        print("⚠️  OpenAI not configured - skipping analysis")
        return None
    
    openai_config = get_openai_config()
    call_type = get_call_type(call_type_id)
    
    logger.debug(f"OpenAI config: model={openai_config.get('model')}, enabled={openai_config.get('enabled')}")
    logger.debug(f"API key present: {bool(openai_config.get('api_key'))}")
    logger.debug(f"API key length: {len(openai_config.get('api_key', ''))}")
    
    # Load context files if specified
    context = ""
    if 'context_files' in call_type:
        context = load_context_files(call_type['context_files'])
        if context:
            logger.info(f"Loaded context for call type '{call_type_id}'")
            print(f"📚 Loaded {len(call_type['context_files'])} context file(s)")
    
    # Get the prompt - handle template for 1:1s
    if call_type.get('requires_person_name') and person_name:
        prompt = call_type.get('prompt_template', '').format(person_name=person_name)
    else:
        prompt = call_type.get('prompt', '')
    
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
    provider = openai_config.get('provider', 'openai')
    if provider == 'databricks':
        model = openai_config.get('databricks_model', 'databricks-gpt-5-2')
    else:
        model = openai_config.get('model', 'gpt-4o')
    
    logger.info(f"Sending to ChatGPT: provider={provider}, model={model}, transcript_len={len(transcript)}")
    print("🤖 Analyzing transcript with ChatGPT...")
    print(f"   Provider: {provider}")
    print(f"   Model: {model}")
    print(f"   Call type: {call_type.get('name', call_type_id)}")
    if person_name:
        print(f"   Person: {person_name}")
    print()
    
    try:
        import openai
        logger.debug(f"OpenAI library version: {openai.__version__}")
        
        # Create client based on provider
        if provider == 'databricks':
            profile = openai_config.get('databricks_profile')
            if not profile:
                logger.error("Databricks profile not configured")
                print("❌ Databricks profile not configured in openai.databricks_profile", file=sys.stderr)
                return None
            
            client, host_or_error = get_databricks_openai_client(profile)
            if not client:
                logger.error(f"Databricks connection failed: {host_or_error}")
                print(f"❌ Databricks auth failed: {host_or_error}", file=sys.stderr)
                print(f"   Run: databricks auth login --profile {profile}", file=sys.stderr)
                return None
            
            logger.info(f"Using Databricks: {host_or_error}")
        else:
            # Direct OpenAI
            logger.debug("Creating direct OpenAI client...")
            client = openai.OpenAI(api_key=openai_config['api_key'])
            logger.info("Using direct OpenAI API")
        
        logger.info("Calling ChatGPT API...")
        
        # Build API parameters
        api_params = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message}
            ],
            "temperature": 0.3,  # Lower temperature for more consistent analysis
        }
        
        # Use max_completion_tokens for newer models (o1, gpt-5, etc.)
        # Databricks models typically use max_tokens
        if provider == 'openai' and model.startswith(('o1', 'gpt-5', 'gpt-4o-')):
            api_params["max_completion_tokens"] = 4000
        else:
            api_params["max_tokens"] = 4000
        
        response = client.chat.completions.create(**api_params)
        logger.info("ChatGPT API call successful")
        
        analysis = response.choices[0].message.content
        logger.info(f"ChatGPT response received: {len(analysis)} chars")
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
        
        return analysis
        
    except ImportError as e:
        logger.error(f"OpenAI package not installed: {e}")
        logger.error(traceback.format_exc())
        print("❌ OpenAI package not installed. Run: pip install openai", file=sys.stderr)
        return None
    except Exception as e:
        logger.error(f"ChatGPT analysis failed: {e}")
        logger.error(traceback.format_exc())
        print(f"❌ ChatGPT analysis failed: {e}", file=sys.stderr)
        return None


# ─── Process Existing Video ──────────────────────────────────────────────────

def process_existing_video(
    video_path: str,
    title: str = None,
    keep_video: bool = False,
    diarize: bool = None,
    call_type: str = None,
    person_name: str = None
):
    """
    Process an existing video file - extract audio, transcribe, and analyze.
    
    Args:
        video_path: Path to the video file
        title: Optional title for the recording (derived from filename if not provided)
        keep_video: If True, don't delete the original video after processing
        diarize: Enable speaker diarization (default: use saved setting)
        call_type: Call type ID for ChatGPT analysis
        person_name: Person name for 1:1 meetings
    """
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
    
    # Run ChatGPT analysis if enabled
    if is_openai_enabled():
        print()
        transcript = load_transcript(paths['transcript_dir'])
        if transcript:
            analyze_with_chatgpt(
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
    if is_openai_enabled():
        print(f"🤖 Analysis: {paths['output_dir']}/chatgpt_analysis.md")
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
    and ChatGPT analysis.
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
            video_file.unlink()
            logger.debug("Video file deleted")
        else:
            logger.error(f"Audio extraction failed - file missing or empty")
            notify("Processing Error", f"Audio extraction failed for: {title}")
            return False
        
        # Run WhisperX transcription
        logger.info("Starting WhisperX transcription...")
        run_whisperx(audio_file, paths['transcript_dir'], diarize=diarize)
        logger.info("WhisperX transcription complete")
        
        # Run ChatGPT analysis if enabled
        logger.info(f"Checking OpenAI status: enabled={is_openai_enabled()}")
        if is_openai_enabled():
            logger.info("OpenAI is enabled, loading transcript...")
            transcript = load_transcript(paths['transcript_dir'])
            if transcript:
                logger.info(f"Transcript loaded: {len(transcript)} chars")
                logger.debug(f"Transcript preview: {transcript[:200]}...")
                
                analysis = analyze_with_chatgpt(
                    transcript=transcript,
                    call_type_id=call_type,
                    person_name=person_name,
                    output_dir=paths['output_dir'],
                    title=title
                )
                
                if analysis:
                    logger.info("ChatGPT analysis completed successfully")
                    notify("Analysis Complete", f"Finished: {title}")
                else:
                    logger.warning("ChatGPT analysis returned None")
                    notify("Transcription Complete", f"Finished: {title} (analysis failed)")
            else:
                logger.warning("No transcript found for analysis")
                notify("Transcription Complete", f"Finished: {title} (no transcript for analysis)")
        else:
            logger.info("OpenAI not enabled, skipping analysis")
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
        else:
            remaining.append(arg)
        i += 1
    
    return remaining, flags


def main():
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        diarize_status = "enabled" if get_diarize_setting() else "disabled"
        openai_status = "enabled" if is_openai_enabled() else "disabled"
        
        print("Usage: whisperx_recorder.py <command> [args] [flags]")
        print()
        print("Commands:")
        print("  start [title]           - Start recording (prompts if not provided)")
        print("  stop                    - Stop recording and transcribe")
        print("  process <video> [title] - Process existing video file")
        print("  analyze <folder>        - Run ChatGPT analysis on existing transcript")
        print("  config diarize <on|off> - Set default diarization preference")
        print("  types                   - List available call types")
        print("  status                  - Get current status (JSON output)")
        print("  logs [N]                - Show last N log entries (default: 50)")
        print("  logs-clear              - Clear all logs")
        print()
        print("Flags:")
        print("  --no-diarize            - Skip speaker diarization (faster, offline)")
        print("  --diarize               - Enable speaker diarization")
        print("  --call-type <type>      - Specify call type (e.g., team_meeting)")
        print("  --person <name>         - Person name (for 1:1 meetings)")
        print()
        print(f"Current diarization default: {diarize_status}")
        print(f"OpenAI analysis: {openai_status}")
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
            print("Flags: --call-type <type>, --person <name>, --no-diarize", file=sys.stderr)
            sys.exit(1)
        
        video_path = args[1]
        title = ' '.join(args[2:]) if len(args) > 2 else None
        diarize = flags.get('diarize', get_diarize_setting())
        call_type = flags.get('call_type')
        person_name = flags.get('person_name')
        success = process_existing_video(
            video_path, title,
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
        status['openai_enabled'] = is_openai_enabled()
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
        # Manually run ChatGPT analysis on existing transcript
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
        print(f"📋 Running ChatGPT analysis on: {recording_path.name}")
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
        analysis = analyze_with_chatgpt(
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
