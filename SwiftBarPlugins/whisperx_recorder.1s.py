#!/Users/smitty.weygant/anaconda3/envs/whisperx-recorder/bin/python
# -*- coding: utf-8 -*-
# <xbar.title>WhisperX Recorder</xbar.title>
# <xbar.version>v3.0</xbar.version>
# <xbar.author>Smitty Weygant</xbar.author>
# <xbar.desc>Record meetings with OBS and transcribe with WhisperX + ChatGPT analysis.</xbar.desc>
# <xbar.dependencies>python,obs-cmd,whisperx,openai</xbar.dependencies>
# <xbar.refreshTime>1s</xbar.refreshTime>

"""
SwiftBar Plugin for WhisperX Recording

Shows recording status in menu bar with controls to start/stop recording.
Includes:
- Call type selection with customized ChatGPT prompts
- Diarization toggle for low-bandwidth situations
- Processing queue status
"""

import json
from pathlib import Path

# Path to the backend script
SCRIPT_DIR = Path(__file__).parent.parent / "processing-pipeline"
RECORDER_SCRIPT = SCRIPT_DIR / "whisperx_recorder.py"
STATE_FILE = Path.home() / ".config/whisperx/recording_state.json"
PROCESSING_STATE_FILE = Path.home() / ".config/whisperx/processing_state.json"
USER_SETTINGS_FILE = Path.home() / ".config/whisperx/settings.json"
DEFAULT_CONFIG_FILE = SCRIPT_DIR / "config.default.json"

# Icons
ICON_IDLE = "🎙️"
ICON_RECORDING = "🔴"
ICON_PROCESSING = "⏳"

# Wrapper script (simple path, no special chars)
# This avoids SwiftBar issues with long OneDrive paths
RECORDER_CMD = Path.home() / ".local/bin/whisperx-recorder"


def load_state() -> dict:
    """Load recording state directly from file for faster access."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}


def load_processing_jobs() -> list:
    """Load all active processing jobs, filtering out dead processes."""
    if not PROCESSING_STATE_FILE.exists():
        return []
    
    try:
        import os
        with open(PROCESSING_STATE_FILE, 'r') as f:
            data = json.load(f)
        
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
                    pass
        
        # Update file if we removed any dead jobs
        if len(active_jobs) != len(jobs):
            with open(PROCESSING_STATE_FILE, 'w') as f:
                json.dump({'jobs': active_jobs}, f, indent=2)
        
        return active_jobs
    except:
        return []


def load_settings() -> dict:
    """Load settings with cascading priority: defaults -> user overrides."""
    config = {
        'transcription': {'diarize': True},
        'openai': {'enabled': False},
        'call_types': {}
    }  # Fallback
    
    # Load project defaults
    if DEFAULT_CONFIG_FILE.exists():
        try:
            with open(DEFAULT_CONFIG_FILE, 'r') as f:
                project_config = json.load(f)
                if 'transcription' in project_config:
                    config['transcription'].update(project_config['transcription'])
                if 'openai' in project_config:
                    config['openai'].update(project_config['openai'])
                if 'call_types' in project_config:
                    config['call_types'] = project_config['call_types']
        except:
            pass
    
    # Load user overrides
    if USER_SETTINGS_FILE.exists():
        try:
            with open(USER_SETTINGS_FILE, 'r') as f:
                user_config = json.load(f)
                if 'transcription' in user_config:
                    config['transcription'].update(user_config['transcription'])
                if 'openai' in user_config:
                    config['openai'].update(user_config['openai'])
        except:
            pass
    
    return config


def is_openai_enabled(settings: dict) -> bool:
    """Check if OpenAI integration is enabled."""
    openai_config = settings.get('openai', {})
    return (
        openai_config.get('enabled', False) and
        bool(openai_config.get('api_key'))
    )


def truncate_title(title: str, max_len: int = 25) -> str:
    """Truncate title for menu bar display."""
    if len(title) <= max_len:
        return title
    return title[:max_len - 1] + "…"


def main():
    """Main plugin entry point."""
    state = load_state()
    processing_jobs = load_processing_jobs()
    settings = load_settings()
    is_recording = state.get('recording', False)
    processing_count = len(processing_jobs)
    diarize_enabled = settings.get('transcription', {}).get('diarize', True)
    openai_enabled = is_openai_enabled(settings)
    call_types = settings.get('call_types', {})
    
    # ─── Menu Bar Title ───────────────────────────────────────────────────────
    if is_recording:
        title = state.get('title', 'Recording')
        # Also show processing count if any
        if processing_count > 0:
            print(f"{ICON_RECORDING} {truncate_title(title)} ({processing_count}) | color=red")
        else:
            print(f"{ICON_RECORDING} {truncate_title(title)} | color=red")
    elif processing_count > 0:
        if processing_count == 1:
            proc_title = processing_jobs[0].get('title', 'Processing')
            print(f"{ICON_PROCESSING} {truncate_title(proc_title)} | color=orange")
        else:
            print(f"{ICON_PROCESSING} {processing_count} Processing | color=orange")
    else:
        # Show status indicators in idle state
        diarize_indicator = "•" if diarize_enabled else "○"
        ai_indicator = "🤖" if openai_enabled else ""
        print(f"{ICON_IDLE} Ready {diarize_indicator}{ai_indicator}")
    
    # ─── Dropdown Menu ────────────────────────────────────────────────────────
    print("---")
    
    if is_recording:
        # Recording in progress - show stop option
        title = state.get('title', 'Recording')
        started = state.get('started_at', 'Unknown')
        rec_diarize = state.get('diarize', True)
        call_type = state.get('call_type', 'generic')
        call_type_info = call_types.get(call_type, {})
        call_type_name = call_type_info.get('name', call_type)
        
        print(f"Recording: {title} | color=red")
        print(f"Started: {started[:19]} | size=11")
        print(f"Call Type: {call_type_name} | size=11")
        print(f"Diarization: {'on' if rec_diarize else 'off'} | size=11")
        if openai_enabled:
            print(f"ChatGPT Analysis: enabled | size=11")
        
        print("---")
        print(f"⏹️ Stop Recording | bash={RECORDER_CMD} param1=stop terminal=false refresh=true")
        
    else:
        # Show processing status if any jobs active
        if processing_count > 0:
            print(f"⏳ Processing ({processing_count} job{'s' if processing_count > 1 else ''}) | color=orange")
            for job in processing_jobs:
                proc_title = job.get('title', 'Unknown')
                proc_started = job.get('started_at', 'Unknown')[:19]
                proc_diarize = job.get('diarize', True)
                proc_call_type = job.get('call_type_name', 'Recording')
                diarize_icon = "🎤" if proc_diarize else "📝"
                print(f"--{diarize_icon} {proc_title} | size=12")
                print(f"----Type: {proc_call_type} | size=10 color=gray")
                print(f"----Started: {proc_started} | size=10 color=gray")
            print("---")
        
        # ─── Settings ─────────────────────────────────────────────────────────
        diarize_status = "✓ On" if diarize_enabled else "✗ Off"
        
        print(f"Speaker Diarization: {diarize_status}")
        print(f"--Turn On | bash={RECORDER_CMD} param1=config param2=diarize param3=on terminal=false refresh=true")
        print(f"--Turn Off (faster, offline) | bash={RECORDER_CMD} param1=config param2=diarize param3=off terminal=false refresh=true")
        
        if openai_enabled:
            print(f"🤖 ChatGPT Analysis: Enabled | color=green")
        else:
            print(f"🤖 ChatGPT Analysis: Disabled | color=gray")
        
        print("---")
        
        # ─── Interactive Start (with call type selection) ─────────────────────
        if diarize_enabled:
            print(f"▶️ Start Recording (interactive) | bash={RECORDER_CMD} param1=start terminal=true refresh=true")
        else:
            print(f"▶️ Start Recording (interactive) | bash={RECORDER_CMD} param1=start param2=--no-diarize terminal=true refresh=true")
        
        # ─── Quick Start by Call Type ─────────────────────────────────────────
        print("---")
        print("Quick Start by Call Type:")
        
        # Build diarize flag
        diarize_flag = "" if diarize_enabled else " param5=--no-diarize"
        
        # Dynamic call type menu from config
        for ct_id, ct_info in call_types.items():
            icon = ct_info.get('icon', '📝')
            name = ct_info.get('name', ct_id)
            requires_person = ct_info.get('requires_person_name', False)
            
            if requires_person:
                # 1:1s need terminal for person name input
                if diarize_enabled:
                    print(f"--{icon} {name} (enter name) | bash={RECORDER_CMD} param1=start param2=--call-type param3={ct_id} terminal=true refresh=true")
                else:
                    print(f"--{icon} {name} (enter name) | bash={RECORDER_CMD} param1=start param2=--call-type param3={ct_id} param4=--no-diarize terminal=true refresh=true")
            else:
                # Regular types can quick start
                if diarize_enabled:
                    print(f"--{icon} {name} | bash={RECORDER_CMD} param1=start param2={name} param3=--call-type param4={ct_id} terminal=false refresh=true")
                else:
                    print(f"--{icon} {name} | bash={RECORDER_CMD} param1=start param2={name} param3=--call-type param4={ct_id} param5=--no-diarize terminal=false refresh=true")
    
    # ─── Settings & Info ──────────────────────────────────────────────────────
    print("---")
    print("⚙️ Settings")
    print(f"--Open Config Folder | bash=open param1={Path.home() / '.config/whisperx'} terminal=false")
    print(f"--Open Recordings Folder | bash=open param1={Path.home() / 'OBSRecordings'} terminal=false")
    print("---")
    ai_status = " + ChatGPT" if openai_enabled else ""
    print(f"WhisperX Recorder v3.0{ai_status} | size=10 color=gray")


if __name__ == '__main__':
    main()
