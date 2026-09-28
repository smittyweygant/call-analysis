#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# <xbar.title>WhisperX Recorder</xbar.title>
# <xbar.version>v3.0</xbar.version>
# <xbar.author>Smitty Weygant</xbar.author>
# <xbar.desc>Record meetings with OBS and transcribe with WhisperX + LLM analysis (OpenAI or Anthropic).</xbar.desc>
# <xbar.dependencies>python,obs-cmd,whisperx</xbar.dependencies>
# <xbar.refreshTime>1s</xbar.refreshTime>

"""
SwiftBar Plugin for WhisperX Recording

Shows recording status in menu bar with controls to start/stop recording.
Includes:
- Call type selection with customized LLM prompts
- Diarization toggle for low-bandwidth situations
- Processing queue status
"""

import json
from pathlib import Path

# Path to the backend script
SCRIPT_DIR = Path(__file__).resolve().parent.parent / "processing-pipeline"
RECORDER_SCRIPT = SCRIPT_DIR / "whisperx_recorder.py"
STATE_FILE = Path.home() / ".config/whisperx/recording_state.json"
PROCESSING_STATE_FILE = Path.home() / ".config/whisperx/processing_state.json"
USER_SETTINGS_FILE = Path.home() / ".config/whisperx/settings.json"
DEFAULT_CONFIG_FILE = SCRIPT_DIR / "config.default.json"
OBS_RECORD_DIR = Path.home() / "OBSRecordings"

# Icons
ICON_IDLE = "🎙️"
ICON_RECORDING = "🔴"
ICON_PROCESSING = "⏳"

# Wrapper script (simple path, no special chars)
# This avoids SwiftBar issues with long OneDrive paths
RECORDER_CMD = Path.home() / ".local/bin/whisperx-recorder"

# Classifier-allowed call types (primary quick-start menu)
ALLOWED_TYPES = [
    'one_on_one_bryan',
    'one_on_one_tyler',
    'one_on_one_generic',
    'customer_meeting',
    'customer_poc_planning',
    'internal_project',
    'default_generic',
]


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


def load_triage_items() -> list:
    """Scan OBS_RECORD_DIR for needs_triage.json markers. Return list of dicts with 'folder', 'meeting_title', 'classifier_output'."""
    if not OBS_RECORD_DIR.exists():
        return []

    try:
        # Get up to 20 most recent subdirectories
        subdirs = sorted(
            [d for d in OBS_RECORD_DIR.iterdir() if d.is_dir()],
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )[:20]

        triage_items = []
        for folder in subdirs:
            triage_file = folder / "needs_triage.json"
            if triage_file.exists():
                try:
                    with open(triage_file, 'r') as f:
                        triage_data = json.load(f)
                    triage_items.append({
                        'folder': str(folder),
                        'meeting_title': triage_data.get('meeting_title', folder.name),
                        'classifier_output': triage_data.get('classifier_output', {})
                    })
                except:
                    pass

        return triage_items
    except:
        return []


def load_settings() -> dict:
    """Load settings with cascading priority: defaults -> user overrides."""
    config = {
        'transcription': {'diarize': False},
        'recording': {'keep_video': False, 'keep_audio': True},
        'analysis': {'auto_classify': False, 'force_manual_all': False},
        'swiftbar': {'show_legacy_call_types': False},
        'llm': {'enabled': False, 'auto_analyze': False},
        'call_types': {},
    }  # Fallback

    # Load project defaults
    if DEFAULT_CONFIG_FILE.exists():
        try:
            with open(DEFAULT_CONFIG_FILE, 'r') as f:
                project_config = json.load(f)
                if 'transcription' in project_config:
                    config['transcription'].update(project_config['transcription'])
                if 'recording' in project_config:
                    config['recording'].update(project_config['recording'])
                if 'analysis' in project_config:
                    config['analysis'].update(project_config['analysis'])
                if 'swiftbar' in project_config:
                    config['swiftbar'].update(project_config['swiftbar'])
                if 'llm' in project_config:
                    config['llm'].update(project_config['llm'])
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
                if 'recording' in user_config:
                    config['recording'].update(user_config['recording'])
                if 'analysis' in user_config:
                    config['analysis'].update(user_config['analysis'])
                if 'swiftbar' in user_config:
                    config['swiftbar'].update(user_config['swiftbar'])
                if 'llm' in user_config:
                    config['llm'].update(user_config['llm'])
        except:
            pass

    return config


def is_llm_configured(settings: dict) -> bool:
    """Check if LLM analysis is enabled and has the credential its provider needs."""
    llm_config = settings.get('llm', {})
    if not llm_config.get('enabled', False):
        return False
    provider = llm_config.get('provider', 'openai')
    if provider == 'anthropic':
        return bool(llm_config.get('anthropic_api_key'))
    elif provider == 'claude_cli':
        return True  # auth is the CLI's session login, not a stored credential
    return bool(llm_config.get('api_key'))


def is_auto_analyze_enabled(settings: dict) -> bool:
    """Whether analysis actually runs automatically after a recording, not just configured."""
    return is_llm_configured(settings) and settings.get('llm', {}).get('auto_analyze', False)


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
    # Folders currently being re-triaged in the background (see
    # analyze-auto-async) - hide their stale "needs triage" entry while a
    # job is actively working on them, rather than showing both at once.
    retriaging_folders = {job['folder'] for job in processing_jobs if job.get('folder')}
    triage_items = [item for item in load_triage_items() if item['folder'] not in retriaging_folders]
    triage_count = len(triage_items)
    is_recording = state.get('recording', False)
    processing_count = len(processing_jobs)
    diarize_enabled = settings.get('transcription', {}).get('diarize', False)
    llm_configured = is_llm_configured(settings)
    auto_analyze_enabled = is_auto_analyze_enabled(settings)
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
        if triage_count > 0:
            print(f"{ICON_IDLE} Ready ⚠️ {triage_count} | color=orange")
        else:
            diarize_indicator = "•" if diarize_enabled else "○"
            ai_indicator = "🤖" if auto_analyze_enabled else ""
            print(f"{ICON_IDLE} Ready {diarize_indicator}{ai_indicator}")
    
    # ─── Dropdown Menu ────────────────────────────────────────────────────────
    print("---")
    
    if is_recording:
        # Recording in progress - show stop option
        title = state.get('title', 'Recording')
        started = state.get('started_at', 'Unknown')
        rec_diarize = state.get('diarize', False)
        call_type = state.get('call_type', 'generic')
        call_type_info = call_types.get(call_type, {})
        call_type_name = call_type_info.get('name', call_type)
        
        print(f"Recording: {title} | color=red")
        print(f"Started: {started[:19]} | size=11")
        print(f"Call Type: {call_type_name} | size=11")
        print(f"Diarization: {'on' if rec_diarize else 'off'} | size=11")
        if auto_analyze_enabled:
            print(f"LLM Analysis: auto-run on completion | size=11")
        
        print("---")
        print(f"⏹️ Stop Recording | bash={RECORDER_CMD} param1=stop terminal=false refresh=true")
        
    else:
        # Show processing status if any jobs active
        if processing_count > 0:
            print(f"⏳ Processing ({processing_count} job{'s' if processing_count > 1 else ''}) | color=orange")
            for job in processing_jobs:
                proc_title = job.get('title', 'Unknown')
                proc_started = job.get('started_at', 'Unknown')[:19]
                proc_diarize = job.get('diarize', False)
                proc_call_type = job.get('call_type_name', 'Recording')
                diarize_icon = "🎤" if proc_diarize else "📝"
                print(f"--{diarize_icon} {proc_title} | size=12")
                print(f"----Type: {proc_call_type} | size=10 color=gray")
                print(f"----Started: {proc_started} | size=10 color=gray")
            print("---")
        
        # ─── Settings ─────────────────────────────────────────────────────────

        # Needs Triage section
        if triage_count > 0:
            print(f"⚠️ Needs Triage ({triage_count}) | color=orange")
            for item in triage_items:
                folder = item['folder']
                title = item['meeting_title']
                classifier_out = item.get('classifier_output', {})
                confidence = classifier_out.get('confidence', 0.0)
                reason = classifier_out.get('reason', '')
                # Top-level entry per triage item
                print(f"--{truncate_title(title, 30)} | size=12")
                print(f"----Confidence: {confidence:.2f} | size=10 color=gray")
                if reason:
                    print(f"----{truncate_title(reason, 40)} | size=10 color=gray")
                # Force-type submenu
                print(f"----Classify as: | size=10 color=gray")
                # Emit each allowed type as a clickable item that re-triages in
                # the background (analyze-auto-async), so the menu can show it
                # as an active processing job instead of leaving this same
                # "needs triage" entry up for as long as re-classification takes.
                for ct_id in ALLOWED_TYPES:
                    ct = call_types.get(ct_id, {})
                    icon = ct.get('icon', '📝')
                    name = ct.get('name', ct_id)
                    print(f"-----{icon} {name} | bash={RECORDER_CMD} param1=analyze-auto-async param2={folder} param3={ct_id} param4={title} terminal=false refresh=true")
            print("---")

        # ─── Settings Group ───────────────────────────────────────────────────
        print("Settings:")

        # Diarization toggle
        diarize_next = "off" if diarize_enabled else "on"
        diarize_hint = " (faster, offline)" if diarize_enabled else ""
        print(f"Speaker Diarization{diarize_hint} | checked={'true' if diarize_enabled else 'false'} bash={RECORDER_CMD} param1=config param2=diarize param3={diarize_next} terminal=false refresh=true")

        # Recording toggles
        recording_cfg = settings.get('recording', {})
        keep_audio = recording_cfg.get('keep_audio', True)
        keep_video = recording_cfg.get('keep_video', False)

        audio_next = "off" if keep_audio else "on"
        print(f"Keep audio after processing | checked={'true' if keep_audio else 'false'} bash={RECORDER_CMD} param1=config param2=keep_audio param3={audio_next} terminal=false refresh=true")

        video_next = "off" if keep_video else "on"
        print(f"Keep video after processing | checked={'true' if keep_video else 'false'} bash={RECORDER_CMD} param1=config param2=keep_video param3={video_next} terminal=false refresh=true")

        # Analysis toggles
        analysis_cfg = settings.get('analysis', {})
        auto_classify = analysis_cfg.get('auto_classify', False)
        force_manual = analysis_cfg.get('force_manual_all', False)

        auto_classify_next = "off" if auto_classify else "on"
        print(f"Auto-classify after transcription | checked={'true' if auto_classify else 'false'} bash={RECORDER_CMD} param1=config param2=auto_classify param3={auto_classify_next} terminal=false refresh=true")

        force_manual_next = "off" if force_manual else "on"
        print(f"Force manual triage for all calls | checked={'true' if force_manual else 'false'} bash={RECORDER_CMD} param1=config param2=force_manual_all param3={force_manual_next} terminal=false refresh=true")

        # SwiftBar toggles
        swiftbar_cfg = settings.get('swiftbar', {})
        show_legacy = swiftbar_cfg.get('show_legacy_call_types', False)

        show_legacy_next = "off" if show_legacy else "on"
        print(f"Show legacy call types | checked={'true' if show_legacy else 'false'} bash={RECORDER_CMD} param1=config param2=show_legacy_call_types param3={show_legacy_next} terminal=false refresh=true")

        # LLM Analysis checkbox
        llm_cfg = settings.get('llm', {})
        llm_enabled = llm_cfg.get('enabled', False)
        llm_enabled_next = "off" if llm_enabled else "on"
        print(f"🤖 Enable LLM Analysis | checked={'true' if llm_enabled else 'false'} bash={RECORDER_CMD} param1=config param2=llm_enabled param3={llm_enabled_next} terminal=false refresh=true")

        # Provider (Claude account) submenu
        claude_account = llm_cfg.get('account', 'personal')
        print("Provider:")
        print(f"--Claude - Work | checked={'true' if claude_account == 'work' else 'false'} bash={RECORDER_CMD} param1=config-set param2=claude_account param3=work terminal=false refresh=true")
        print(f"--Claude - Personal (default) | checked={'true' if claude_account == 'personal' else 'false'} bash={RECORDER_CMD} param1=config-set param2=claude_account param3=personal terminal=false refresh=true")

        print("---")

        # ─── Quick Start ───────────────────────────────────────────────────────
        print(f"▶️ Quick Start | bash={RECORDER_CMD} param1=start param2=--call-type param3=default_generic terminal=false refresh=true")

        # ─── Interactive Start (with call type selection) ─────────────────────
        if diarize_enabled:
            print(f"▶️ Start Recording (choose type) | bash={RECORDER_CMD} param1=start terminal=true refresh=true")
        else:
            print(f"▶️ Start Recording (choose type) | bash={RECORDER_CMD} param1=start param2=--no-diarize terminal=true refresh=true")
        
        # ─── Quick Start by Call Type ─────────────────────────────────────────
        print("---")
        print("Quick Start by Call Type:")
        
        # Build diarize flag
        diarize_flag = "" if diarize_enabled else " param5=--no-diarize"

        # Separate primary (classifier-allowed) and legacy call types
        primary_types = {}
        legacy_types = {}
        for ct_id, ct_info in call_types.items():
            if ct_id in ALLOWED_TYPES:
                primary_types[ct_id] = ct_info
            else:
                legacy_types[ct_id] = ct_info

        # Emit primary types first
        for ct_id, ct_info in primary_types.items():
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

        # Emit legacy types in a nested submenu (guarded by show_legacy setting)
        show_legacy = settings.get('swiftbar', {}).get('show_legacy_call_types', False)
        if show_legacy and legacy_types:
            print("--Legacy call types")
            for ct_id, ct_info in legacy_types.items():
                icon = ct_info.get('icon', '📝')
                name = ct_info.get('name', ct_id)
                requires_person = ct_info.get('requires_person_name', False)

                if requires_person:
                    # 1:1s need terminal for person name input
                    if diarize_enabled:
                        print(f"----{icon} {name} (enter name) | bash={RECORDER_CMD} param1=start param2=--call-type param3={ct_id} terminal=true refresh=true")
                    else:
                        print(f"----{icon} {name} (enter name) | bash={RECORDER_CMD} param1=start param2=--call-type param3={ct_id} param4=--no-diarize terminal=true refresh=true")
                else:
                    # Regular types can quick start
                    if diarize_enabled:
                        print(f"----{icon} {name} | bash={RECORDER_CMD} param1=start param2={name} param3=--call-type param4={ct_id} terminal=false refresh=true")
                    else:
                        print(f"----{icon} {name} | bash={RECORDER_CMD} param1=start param2={name} param3=--call-type param4={ct_id} param5=--no-diarize terminal=false refresh=true")
    
    # ─── Settings & Info ──────────────────────────────────────────────────────
    print("---")
    print("⚙️ Settings")
    print(f"--Open Config Folder | bash=open param1={Path.home() / '.config/whisperx'} terminal=false")
    print(f"--Open Recordings Folder | bash=open param1={Path.home() / 'OBSRecordings'} terminal=false")
    print("---")
    ai_status = " + LLM auto-analyze" if auto_analyze_enabled else ""
    print(f"WhisperX Recorder v3.0{ai_status} | size=10 color=gray")


if __name__ == '__main__':
    main()
