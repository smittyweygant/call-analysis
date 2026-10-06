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

### Phase 9: Google Drive Integration (January 2026)

**Goal:** Auto-upload analysis files to Google Drive for easy sharing

**Implementation:**
- Service account authentication for Shared Drives
- Auto-create folders per call type
- Convert markdown to HTML for Google Docs formatting
- Document naming: `<Call Type> <yy_mm_dd> - <title>`

**Configuration:**
```json
{
  "gdrive": {
    "enabled": true,
    "service_account_file": "service-account.json",
    "shared_drive_id": "DRIVE_ID"
  }
}
```

**Key Decision:** Use Shared Drive (not My Drive) because service accounts have no storage quota for regular Drive.

### Phase 10: External Prompt Files (January 2026)

**Problem:** Long prompts cluttered the config file; prompts needed separate versioning

**Solution:** `prompt_file` config option to load prompts from external markdown files

```json
{
  "interview_fe_hm": {
    "context_files": ["Agent_context/..."],
    "prompt_file": "Agent_prompts/hm_interview_fe_evaluation_prompt.md"
  }
}
```

**Additional Features:**
- `name_prompt` - Custom input prompts (e.g., "Enter customer name" vs "Enter person's name")
- PDF context file support via `pypdf` library
- Customer Meeting call type with company name prompt

---

### Phase 11: Inference-driven analysis + Obsidian vault write (September 2026)

**Goal:** Eliminate manual call-type selection at recording start, persist analyses to the vault instead of only to `~/OBSRecordings/…` or Google Drive, and retire the 1Password dependency for the analysis step.

**Problem:** The pipeline required choosing a call type upfront (or falling back to a generic default), which meant either interrupting the start flow with a prompt or getting a poorly-matched analysis. Completed analyses lived only in the local recording folder unless `gdrive.enabled` was turned on, with no default durable home. The direct Anthropic SDK path pulled its API key from 1Password on every run, adding a dependency and a possible `op` session-expiry failure mode to routine analysis.

**Implementation:**
- New `analyze-auto` subcommand runs classify → analyze → vault-write as three separate `claude -p` invocations. It's the default post-transcript flow, normally triggered automatically after `stop` (via `analysis.auto_classify`) or after `process`.
- The classifier compares the transcript against a registry of seven current-focus call types (each carrying an `inference_hint`) and returns a confidence score. At or above `analysis.auto_analyze_confidence` (default `0.75`) it proceeds to analysis automatically; below that, or with `analysis.force_manual_all` set, it writes `needs_triage.json` and stops, surfacing the recording in SwiftBar's "Needs Triage" section for manual classification.
- Added the `claude_cli` LLM provider, which shells to `claude -p` instead of calling the Anthropic or OpenAI SDKs directly. It's the new default in `llm.provider`; `anthropic` and `openai` remain as configurable side-by-side options.
- Added the `analysis` config block (`auto_classify`, `auto_analyze_confidence`, `force_manual_all`, `classifier_prompt_file`, `vault_write_prompt_file`, `vault_path`) and the `swiftbar` config block (`show_legacy_call_types`).
- After analysis, a vault-write `claude -p` session follows the routing conventions in the vault's own `CLAUDE.md`, landing the result under `People/<Name>.md`, `Customers/<Company>.md`, `Projects/<Project>.md`, or `Inbox.md`. Google Drive upload remains available but is now a secondary destination rather than the durable one.
- `recording.keep_audio` defaults to `true` (video still defaults to deleted); both are toggleable via `whisperx-recorder config keep_audio on/off` and `config keep_video on/off`.
- Purged 14 legacy call types from `config.default.json` in favor of the seven current-focus ones; their prompt and context files moved to `Agent_prompts/legacy/` and `Agent_context/legacy/` in the prompts repo.
- SwiftBar plugin gained a no-prompt "Quick Start" item, six unified checkbox toggles for settings, and the "Needs Triage" section with a per-recording "Classify as…" submenu.

**Trade-offs:** Model selection for the analysis, classification, and vault-write steps now flows through Claude Code's own configuration rather than an explicit `llm.model` field, so per-run model choice is less granular than the direct-SDK providers offer. Cost accounting also shifts from metered direct API usage to whatever the local `claude` CLI session is authenticated against (a Claude subscription rather than pay-per-token API billing).

**Decision:** Worth it. A single auth path (the already-signed-in `claude` CLI) removes both the 1Password prompt and the API key management that came with `anthropic`/`openai`, and the Obsidian vault is a better long-term home for these analyses than scattered local Markdown files or a Drive folder that required opting in.

---

### Phase 12: Call-type-driven folder naming + triage escalation (October 2026)

**Goal:** Stop recordings from sitting under a generic placeholder name once their call type is known, and make an inconclusive classification visibly actionable instead of just a silent `needs_triage.json` marker.

**Problem:** A recording's folder/file names were fixed at recording start, before the transcript existed — so an unclassified quick-start recording kept a generic "Recording" name even after `analyze-auto` later resolved its real call type. And when classification came back inconclusive, the only signal was an entry in SwiftBar's "Needs Triage" submenu — easy to miss if you weren't actively looking at the menu bar.

**Implementation:**
- An untyped recording (no `--call-type` given up front) now starts out named `Meeting_<HHMM>` instead of a generic "Recording" label, so every meeting still gets its own folder regardless of whether a type was known at record time.
- Once `analyze-auto` classifies a recording with confidence at or above `analysis.auto_analyze_confidence`, it renames the recording's whole folder in place (`_rename_folder_for_call_type` in `whisperx_recorder.py`) to `<date>_<CallTypeName>[ - <entity>]` — a plain directory rename, so everything inside (transcript, analysis file, metadata, calendar snapshot) moves together. This has to happen after `analyze_with_llm` writes the analysis file but before the vault-write step, which needs an absolute transcript path resolved against the final location.
- When classification is inconclusive (low confidence, or the classifier call itself fails) rather than deliberately blanket-triaged via `force_manual_all`, a new `write_triage_task_to_vault()` step fires a `claude -p` call that appends a dated checkbox task to the vault's daily note, asking for either a manual `--call-type` pick or a brand-new call type recommendation — reusing the classifier's own `reason` field rather than hardcoding any recommendation heuristic in Python.
- `get_call_type()`'s fallback key was corrected to try `default_generic` (used by the auto-classify pipeline) before `generic` (the public template's default id), so a missing/legacy call type id degrades gracefully under either naming convention.

**Trade-off:** Only the enclosing folder gets renamed — the files inside it keep the timestamp-based names they were created with. Renaming every internal file to match would add real risk (stale paths mid-background-job) for little practical benefit, since the folder name alone already disambiguates the recording in a file listing.

**Decision:** Worth it. The placeholder name was previously permanent once a recording wasn't given a type upfront; now it only persists for recordings that genuinely need a human to look at them.

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
| `google-api-python-client` | Google Drive API |
| `google-auth` | Google authentication |
| `google-auth-oauthlib` | OAuth2 flow |
| `openai` | ChatGPT API |
| `databricks-sdk` | Databricks OAuth authentication |
| `pypdf` | PDF context file parsing |
| `markdown` | Markdown to HTML conversion for GDrive |
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
  "gdrive": {
    "enabled": false,
    "service_account_file": "service-account.json",
    "shared_drive_id": "DRIVE_ID"
  },
  "openai": {
    "provider": "openai",
    "api_key": "YOUR_OPENAI_KEY",
    "model": "gpt-4o",
    "enabled": true,
    "databricks_profile": "YOUR_PROFILE",
    "databricks_model": "databricks-gpt-5-2"
  },
  "call_types": {
    "example": {
      "name": "Example",
      "icon": "📝",
      "context_files": ["path/to/context.md"],
      "prompt_file": "path/to/prompt.md",
      "requires_person_name": true,
      "name_prompt": "Enter name"
    }
  }
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
*Last updated: October 6, 2026 — Call-type-driven folder renaming, Meeting_<HHMM> placeholder naming, Obsidian triage task on inconclusive classification*
*Cursor conversation transcript archived to: `~/.cursor/projects/.../agent-transcripts-archive/`*
