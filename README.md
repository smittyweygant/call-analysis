# WhisperX Call Recording & Transcription

A macOS menu bar application for recording calls/meetings with OBS, transcribing them with WhisperX, and analyzing transcripts with an LLM (Claude CLI, OpenAI, or Anthropic).

## Features

- 🎙️ **One-click recording** via SwiftBar menu bar plugin, including a no-prompt "Quick Start"
- 📝 **Automatic transcription** using WhisperX (OpenAI Whisper) — the transcript is the default deliverable; diarization and LLM analysis are both opt-in
- 🎤 **Speaker diarization** (optional) - identifies who said what
- 🔊 **Audio retention** - post-transcription audio is kept by default (`recording.keep_audio: true`); video is deleted by default
- 🧭 **Auto-classification** - after transcription, `analyze-auto` classifies the call against a registry of current-focus call types and analyzes automatically at confidence ≥ 0.75 (configurable), otherwise queues it for manual triage in SwiftBar
- 🤖 **LLM analysis** - AI-powered summaries via `claude_cli` (default, shells to `claude -p`), OpenAI, or Anthropic, with customizable prompts
- 📋 **Call type templates** - tailored prompts for different meeting types
- 🧠 **Obsidian vault write** - completed analyses are routed into `~/Obsidian/Smitty's Vault/` (People/Customers/Projects/Inbox) as the primary output destination
- 📤 **Google Drive integration** - optional secondary upload of analysis to Shared Drive as Google Docs
- ⏳ **Background processing** - start new recordings while previous ones transcribe
- 🔔 **macOS notifications** for recording status and completion
- 📁 **Organized output** - recordings organized by date and title

## Architecture

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
                        └──────────────────────┘
                                  │
                                  ▼
                        ┌──────────────────────┐
                        │   analyze-auto        │
                        │   classifier          │
                        │   (`claude -p`)       │
                        └──────────────────────┘
                              │         │
                confidence ≥ 0.75    confidence < 0.75
                              │         │
                              ▼         ▼
                  ┌──────────────────┐ ┌──────────────────────┐
                  │  LLM Analysis    │ │  needs_triage.json    │
                  │                  │ │  (manual classify in  │
                  │                  │ │  SwiftBar)             │
                  └──────────────────┘ └──────────────────────┘
                              │
                              ▼
                  ┌──────────────────────┐        ┌──────────────────────┐
                  │  Obsidian vault write │───────▶│  Google Drive         │
                  │  (`claude -p`)        │ optional│  (Shared Drive, opt.)│
                  └──────────────────────┘        └──────────────────────┘
```

## Requirements

| Component | Purpose | Installation |
|-----------|---------|--------------|
| macOS 15+ | Operating system | - |
| OBS Studio | Video/audio recording | `brew install --cask obs` |
| obs-cmd | CLI control for OBS | **Not on Homebrew** — download the release binary for your architecture from [grigio/obs-cmd](https://github.com/grigio/obs-cmd/releases) (e.g. `obs-cmd-x64-macos.tar.gz` for Intel, `obs-cmd-arm64-macos.tar.gz` for Apple Silicon), `chmod +x`, place on your `PATH` |
| SwiftBar | Menu bar plugin framework | `brew install --cask swiftbar` |
| Python 3.10+ | Runtime | pyenv + venv (or conda if you already use it) — see [Python Environment](USER_GUIDE.md#python-environment). **Intel Macs**: PyTorch 2.2.2 is the last version published for Intel, which caps several other dependency versions; see the troubleshooting section if you hit segfaults or dependency conflicts |
| WhisperX | Speech recognition | `pip install whisperx` |
| ffmpeg | Audio extraction | `brew install ffmpeg` |
| `claude` CLI | Default LLM provider (`claude_cli`), auto-classification, and Obsidian vault write | `claude` on `PATH` — see [claude.ai/download](https://claude.ai/download) |
| LLM API (optional) | Analysis via direct SDK — OpenAI or Anthropic, as an alternative to `claude_cli` | API key required, recommended via [1Password `op://` references](USER_GUIDE.md#secrets-management) rather than plaintext |

## Quick Start

```bash
# 1. Clone repository
git clone <repo-url>
cd call-analysis

# 2. Install OBS + SwiftBar if you haven't already
brew install --cask obs swiftbar

# 3. Run the setup script — creates the pyenv+venv Python environment,
#    installs obs-cmd, writes ~/.local/bin/whisperx-recorder, and points
#    SwiftBar at ~/Documents/SwiftBarPlugins. Safe to re-run.
./setup.sh

# 4. Edit configuration with your credentials — or, better, with
#    op://vault/item/field references resolved via the 1Password CLI at
#    runtime; see USER_GUIDE.md#secrets-management
nano processing-pipeline/config.default.json
```

`setup.sh` covers the common case (pyenv + venv, Apple Silicon or Intel obs-cmd binary). If you use conda instead, or need to do any of this by hand, see [Manual setup](USER_GUIDE.md#manual-setup) in the user guide.

**📖 See [USER_GUIDE.md](USER_GUIDE.md) for detailed setup and usage instructions.**

## Configuration

### Project Defaults (`config.default.json`)

```json
{
  "_comment": "WhisperX Recorder Default Configuration",
  "_docs": "User overrides go in ~/.config/whisperx/settings.json",
  "recording": {
    "output_dir": "~/OBSRecordings",
    "obs_ws_port": "4455",
    "obs_ws_password": "keychain://whisperx-obs-ws-password",
    "keep_video": false,
    "keep_audio": true
  },
  "analysis": {
    "_comment": "Post-transcription classify + vault-write pipeline. Requires `claude` CLI on PATH and Akka MCP authenticated.",
    "auto_classify": true,
    "auto_analyze_confidence": 0.75,
    "force_manual_all": false,
    "classifier_prompt_file": "Agent_prompts/_meta/classifier_prompt.md",
    "vault_write_prompt_file": "Agent_prompts/_meta/vault_write_prompt.md",
    "vault_path": "~/Obsidian/Smitty's Vault"
  },
  "swiftbar": {
    "_comment": "SwiftBar plugin display toggles. Persistent user overrides live in ~/.config/whisperx/settings.json.",
    "show_legacy_call_types": false
  },
  "transcription": {
    "diarize": false,
    "language": "en",
    "device": "cpu",
    "compute_type": "float32",
    "whisperx_path": "~/path/to/call-analysis/processing-pipeline/.venv/bin/whisperx",
    "hf_token": "op://Development/Hugging Face Token/credential"
  },
  "gdrive": {
    "enabled": false,
    "service_account_file": "your-service-account.json",
    "parent_folder_id": "YOUR_DRIVE_FOLDER_ID",
    "_comment": "Folders are auto-created per call_type name"
  },
  "llm": {
    "_provider_comment": "Choose one: `claude_cli` (default; shells to `claude -p`, no 1P key needed), `anthropic` (direct SDK, uses anthropic_api_key), `openai` (direct SDK, uses api_key). Other providers stay configured but dormant.",
    "provider": "claude_cli",
    "enabled": true,
    "claude_cli_model_label": "claude-cli",
    "api_key": "YOUR_OPENAI_API_KEY",
    "model": "gpt-4o",
    "anthropic_api_key": "YOUR_ANTHROPIC_API_KEY",
    "anthropic_model": "claude-sonnet-5",
    "auto_analyze": false
  },
  "call_types": { ... }
}
```

`diarize` and `llm.auto_analyze` both default to `false` — the transcript is the deliverable by default; diarization is opt-in per recording (`--diarize`) or run later on demand (`whisperx-recorder analyze <folder> --call-type X`). `recording.keep_audio` defaults to `true` and `recording.keep_video` defaults to `false`; both are toggleable via `whisperx-recorder config keep_audio on/off` and `config keep_video on/off`. `llm.provider` selects `claude_cli` (default), `openai`, or `anthropic`; only one is active at a time. The `analysis` block controls the auto-classify pipeline described in [USER_GUIDE.md](USER_GUIDE.md#command-line-interface); `swiftbar.show_legacy_call_types` controls whether retired call types reappear in the menu.

Any string value above may instead be an `op://vault/item/field` reference, resolved via the 1Password CLI at the point each secret is used — see [Secrets Management](USER_GUIDE.md#secrets-management).

### User Overrides (`~/.config/whisperx/settings.json`)

Personal settings that override project defaults:

```json
{
  "transcription": {
    "diarize": false
  }
}
```

## Call Types

Current-focus call types (the classifier only chooses among these; legacy types can be reactivated per [USER_GUIDE.md](USER_GUIDE.md#call-types)):

| Type | Icon | Purpose | Prompt file |
|------|------|---------|--------------|
| `customer_meeting` | 🤝 | General customer-facing call — discovery, status, technical discussion | `Agent_prompts/customer_meeting_v2_prompt.md` |
| `one_on_one_bryan` | 🧭 | 1:1 with Bryan Penner (manager) | `Agent_prompts/one_on_one_bryan_prompt.md` |
| `one_on_one_tyler` | 🤝 | 1:1 with Tyler (peer) | `Agent_prompts/one_on_one_tyler_prompt.md` |
| `one_on_one_generic` | 👤 | 1:1 with anyone else (prompts for person name) | `Agent_prompts/one_on_one_generic_prompt.md` |
| `customer_poc_planning` | 🧪 | Customer call scoping/planning a Proof-of-Concept | `Agent_prompts/customer_poc_planning_prompt.md` |
| `internal_project` | 🚧 | Internal Akka project/initiative sync (prompts for project name) | `Agent_prompts/internal_project_prompt.md` |
| `default_generic` | 📝 | Fallback when the classifier can't confidently match another type | `Agent_prompts/default_analysis_prompt.md` |

Call types support:
- **`prompt`** - Inline prompt text
- **`prompt_file`** - Load prompt from external markdown file
- **`context_files`** - Load context from markdown/PDF files
- **`name_prompt`** - Custom input prompt (e.g., "Enter customer name")

Add or customize call types in `config.default.json`. See [USER_GUIDE.md](USER_GUIDE.md#customizing-prompts) for details.

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
    ├── analysis_<timestamp>_<model>.md   (if LLM analysis ran)
    └── needs_triage.json                 (present only if classification confidence was below threshold)
```

A completed analysis is written into `~/Obsidian/Smitty's Vault/` (routed to `People/`, `Customers/`, `Projects/`, or `Inbox.md` depending on call content) as the primary destination; Google Drive upload remains available as an optional secondary destination when `gdrive.enabled` is `true`.

## Project Structure

```
call-analysis/
├── README.md                           # This file
├── USER_GUIDE.md                       # Detailed usage guide
├── .gitignore
├── SwiftBarPlugins/
│   └── whisperx_recorder.1s.py         # Menu bar plugin
├── processing-pipeline/
│   ├── config.default.json.template    # Config template (copy to config.default.json)
│   ├── config.default.json             # Your config (gitignored)
│   ├── requirements.txt                # Python dependencies
│   └── whisperx_recorder.py            # Main backend script
└── examples/                           # Example prompts and context files
    ├── prompts/
    │   └── interview_evaluation_prompt.md
    └── context/
        ├── interview_shared_context.md
        └── interview_rubric.md
```

### Private Prompt Content

The `examples/` folder contains generic templates to help you get started. For proprietary or company-specific prompts, maintain them in a separate private repository:

1. Set `context_base_path` in `~/.config/whisperx/settings.json` to point to your private repo clone
2. Reference files relative to that path in your call type `context_files`

See [USER_GUIDE.md](USER_GUIDE.md#private-prompt-repositories) for detailed setup instructions.

## State & Log Files

Located in `~/.config/whisperx/`:

| File | Purpose |
|------|---------|
| `settings.json` | User configuration overrides (includes `context_base_path` for private prompts) |
| `recording_state.json` | Current recording session |
| `processing_state.json` | Background processing queue |
| `logs/whisperx_recorder.log` | Debug and error logs |

## Dotfiles integration

This app can be bootstrapped end-to-end via `~/development/dotfiles/` (chezmoi-managed). Below is what dotfiles owns vs what stays in this repo. The app is fully usable standalone — README Quick Start and `USER_GUIDE.md` Installation don't require dotfiles.

**Where each artifact lives**

| Artifact | Standalone (this repo) | Via dotfiles |
|---|---|---|
| Wrapper script | Manual `ln -s` or copy to `~/.local/bin/whisperx-recorder` | `executable_dot_local/bin/whisperx-recorder` |
| User settings | Manual copy of `config.default.json.template` to `~/.config/whisperx/settings.json` | `dot_config/whisperx/settings.json.tmpl` |
| System packages | `brew install obs obs-cmd ffmpeg` per README | Dotfiles `Brewfile` |
| Repo clones | `git clone` from README Quick Start | `run_once_after_45-clone-call-analysis-repos.sh` |
| Python venv | Manual per README | `run_once_after_50-setup-call-analysis-venv.sh` |
| OBS websocket Keychain | Manual `security add-generic-password` per USER_GUIDE | `run_once_after_55-seed-obs-keychain.sh` |

**When you change X, do Y**

| Change | Action |
|---|---|
| Add a required Homebrew package | Edit dotfiles `Brewfile` |
| Add a new config-file default | Edit `config.default.json.template` here; optionally also `dot_config/whisperx/settings.json.tmpl` in dotfiles if it should ship as a user default |
| Add a new required secret | Decide `op://` vs `keychain://`; document in this README's Configuration section; add a Keychain seed line to `run_once_after_55-…` if applicable |
| Add a new call-type | Edit `config.default.json` and drop the prompt file in `call-analysis-prompts/Agent_prompts/` — no dotfiles change |
| Rename the wrapper | Update `executable_dot_local/bin/whisperx-recorder` in dotfiles, plus the SwiftBar plugin's `RECORDER_CMD` |

The dotfiles bootstrap is additive automation. Anyone can install this app without ever touching the dotfiles repo by following the Quick Start.

## License

MIT

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request
