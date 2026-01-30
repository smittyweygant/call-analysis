# Call Analysis Project - Development History

This document summarizes the key development decisions and features built during the initial development phase (January 2026).

---

## Project Overview

A macOS menu bar application for recording calls/meetings with OBS, transcribing them with WhisperX, and analyzing transcripts with ChatGPT.

---

## Core Architecture

### Recording Pipeline

```
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│  SwiftBar Menu  │────▶│  whisperx_recorder   │────▶│      OBS        │
│     Plugin      │     │      (Python)        │     │  (via obs-cmd)  │
└─────────────────┘     └──────────────────────┘     └─────────────────┘
                                  │
                                  ▼
                        ┌──────────────────────┐
                        │  Background Process  │
                        │  - Extract audio     │
                        │  - Run WhisperX      │
                        │  - ChatGPT Analysis  │
                        └──────────────────────┘
```

### Key Components

| Component | File | Purpose |
|-----------|------|---------|
| Backend Controller | `processing-pipeline/whisperx_recorder.py` | Main Python script handling all operations |
| SwiftBar Plugin | `SwiftBarPlugins/whisperx_recorder.1s.py` | Menu bar UI for start/stop recording |
| Configuration | `processing-pipeline/config.default.json` | Project-level settings (gitignored) |
| Config Template | `processing-pipeline/config.default.json.template` | Public template for setup |

---

## Feature Development Timeline

### Phase 1: Basic Recording Pipeline

**Initial Goal:** Close OBS at end of `whisperx_action.sh` script

**Evolution:**
- Started with shell script (`whisperx_action.sh`)
- Created Python backend for better control
- Added SwiftBar menu bar integration
- Implemented OBS control via `obs-cmd` WebSocket

### Phase 2: Google Calendar Integration (Attempted)

**Goal:** Auto-detect meeting title and attendees from calendar

**Approaches Tried:**
1. **Service Account** - Failed due to corporate Google Workspace restrictions on domain-wide delegation
2. **Calendar Sharing with Service Account** - Limited to free/busy only by org policy
3. **OAuth2 User Authentication** - Required interactive browser login

**Decision:** Simplified to manual title entry with interactive prompts

**Lesson Learned:** Corporate Google Workspace policies often restrict API access. OAuth2 is most reliable but requires user interaction.

### Phase 3: Configuration System

**Design Decision:** Cascading configuration with three layers

```
1. Hardcoded defaults (fallback in code)
2. config.default.json (project defaults, gitignored)
3. ~/.config/whisperx/settings.json (user overrides)
```

**Rationale:**
- Project config can contain sensitive data (API keys, tokens)
- User can override without modifying repo files
- Backward compatibility with flat settings format (auto-migrates)

### Phase 4: Speaker Diarization Toggle

**Feature:** Optional speaker identification in transcripts

**Implementation:**
- `--diarize` / `--no-diarize` CLI flags
- Persistent setting in config
- SwiftBar toggle in menu

**Trade-offs:**
- **On:** Identifies "who said what" - requires internet, HuggingFace token
- **Off:** Faster, works offline, simpler output

### Phase 5: Call Types & ChatGPT Analysis

**Goal:** Different analysis prompts for different meeting types

**Implementation:**
```json
{
  "call_types": {
    "team_meeting": {
      "name": "Team Meeting",
      "icon": "👥",
      "prompt": "Analyze this team meeting transcript..."
    },
    "one_on_one": {
      "name": "1:1 Meeting",
      "requires_person_name": true,
      "prompt_template": "This is a 1:1 meeting with {person_name}..."
    }
  }
}
```

**Features:**
- Customizable prompts per call type
- Support for `{person_name}` placeholder
- Quick-start menu items by call type
- `--call-type` and `--person` CLI flags

### Phase 6: Background Processing

**Problem:** Transcription takes several minutes, blocking new recordings

**Solution:** Background process queue
- Recording stops → processing spawns in background
- User can immediately start new recording
- macOS notifications for completion
- Processing queue visible in SwiftBar menu

**State Files:**
- `~/.config/whisperx/recording_state.json` - Current recording
- `~/.config/whisperx/processing_state.json` - Background job queue

### Phase 7: Interview Evaluation System

**Goal:** Comprehensive candidate evaluation for FE interviews

**Architecture:**
```
Context Files + Prompt = Full ChatGPT Input

interview_fe_hm:
  ├── fe_interview_context_shared.md (role framework, levels)
  ├── fe_interview_context_hiring_manager.md (HM-specific signals)
  └── hm_interview_fe_evaluation_prompt.md (output structure)

interview_fe_panel:
  ├── fe_interview_context_shared.md (role framework, levels)
  ├── fe_interview_context_panel_presentation_demo.md (panel signals)
  └── panel_presentation_demo_fe_evaluation_prompt.md (output structure)
```

**Features:**
- Multi-file context loading
- Greenhouse question set integration (question IDs for copy/paste)
- Structured evaluation output

### Phase 8: Private Prompts Strategy

**Problem:** Interview prompts contain proprietary company information

**Solution:** Configurable `context_base_path`

```json
// ~/.config/whisperx/settings.json
{
  "context_base_path": "~/call-analysis-prompts"
}
```

**Benefits:**
- Public repo works standalone with generic examples
- Private prompts in separate repo
- No git submodule complexity
- Graceful fallback if files missing

---

## Key Technical Decisions

### Python Environment

- **Conda environment:** `whisperx-recorder` with Python 3.10
- **Hardcoded shebang:** Scripts use full conda Python path
- **Rationale:** WhisperX has complex PyTorch dependencies; conda handles these better

### OBS WebSocket Control

- **Tool:** `obs-cmd` (Rust CLI for OBS WebSocket)
- **Connection:** `obsws://127.0.0.1:4455/{password}`
- **Commands:** `obs-cmd recording start`, `obs-cmd recording stop`

### Audio Processing

```bash
ffmpeg -i video.mov -ar 16000 -ac 1 output.wav
```
- Downsamples to 16kHz mono (WhisperX requirement)
- Original video deleted after successful extraction

### WhisperX Options

```bash
whisperx audio.wav \
  --language en \
  --compute_type float32 \
  --device cpu \
  --output_dir transcript/ \
  --diarize \
  --hf_token $HF_TOKEN
```

---

## CLI Reference (as of final implementation)

```
whisperx_recorder.py <command> [args] [flags]

Commands:
  start [title]           Start recording (prompts if not provided)
  stop                    Stop recording and transcribe
  process <video> [title] Process existing video file
  analyze <folder>        Re-run ChatGPT analysis on existing transcript
  config diarize <on|off> Set default diarization preference
  types                   List available call types
  status                  Get current status (JSON output)

Flags:
  --no-diarize            Skip speaker diarization (faster, offline)
  --diarize               Enable speaker diarization
  --call-type <type>      Specify call type (e.g., team_meeting)
  --person <name>         Person name (for 1:1 meetings)
```

---

## Output Structure

```
~/OBSRecordings/
└── 2026-01-21_Weekly_Standup/
    ├── 2026-01-21_Weekly_Standup_143022.wav
    ├── 2026-01-21_Weekly_Standup_143022_metadata.json
    ├── 2026-01-21_Weekly_Standup_143022_transcript/
    │   ├── *.json  (word-level timestamps)
    │   ├── *.srt   (subtitles)
    │   ├── *.txt   (plain text)
    │   └── *.vtt   (web subtitles)
    └── chatgpt_analysis.md
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `google-api-python-client` | Google Calendar API (attempted) |
| `google-auth` | Google authentication |
| `google-auth-oauthlib` | OAuth2 flow |
| `openai` | ChatGPT API |
| `whisperx` | Speech recognition |
| `ffmpeg` | Audio extraction (system) |
| `obs-cmd` | OBS control (system) |

---

## Configuration Files Reference

### config.default.json (structure)

```json
{
  "recording": {
    "output_dir": "~/OBSRecordings",
    "obs_ws_port": "4455",
    "obs_ws_password": "YOUR_PASSWORD"
  },
  "transcription": {
    "diarize": true,
    "language": "en",
    "device": "cpu",
    "compute_type": "float32",
    "whisperx_path": "~/anaconda3/bin/whisperx",
    "hf_token": "YOUR_HF_TOKEN"
  },
  "openai": {
    "api_key": "YOUR_OPENAI_KEY",
    "model": "gpt-4o",
    "enabled": true
  },
  "call_types": { ... }
}
```

---

## Lessons Learned

1. **Corporate API restrictions** - Always have fallback when relying on external APIs
2. **Background processing** - Essential for good UX with long-running tasks
3. **Cascading config** - Keeps sensitive data out of repos while allowing defaults
4. **Private/public split** - Use `context_base_path` pattern for proprietary content
5. **SwiftBar limitations** - Parameter passing requires careful escaping; use separate params

---

## Related Plan Files

Detailed implementation plans are preserved in `~/.cursor/plans/`:
- `recording_ui_+_calendar_integration_*.plan.md`
- `add_fe_interview_types_*.plan.md`
- `interview_prompts_+_context_*.plan.md`
- `private_prompts_strategy_*.plan.md`

---

*Document generated: January 2026*
*Cursor conversation transcript archived to: `~/.cursor/projects/.../agent-transcripts-archive/`*
