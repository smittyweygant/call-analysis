# WhisperX Call Recording & Transcription

A macOS menu bar application for recording calls/meetings with OBS, transcribing them with WhisperX, and analyzing transcripts with an LLM (OpenAI or Anthropic).

## Features

- 🎙️ **One-click recording** via SwiftBar menu bar plugin
- 📝 **Automatic transcription** using WhisperX (OpenAI Whisper) — the transcript is the default deliverable; diarization and LLM analysis are both opt-in
- 🎤 **Speaker diarization** (optional) - identifies who said what
- 🤖 **LLM analysis** (optional) - AI-powered summaries via OpenAI or Anthropic, with customizable prompts
- 📋 **Call type templates** - tailored prompts for different meeting types
- 📤 **Google Drive integration** - auto-upload analysis to Shared Drive as Google Docs
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
                        │  - LLM Analysis      │
                        │  - Google Drive Upload│
                        └──────────────────────┘
                                  │
                                  ▼
                        ┌──────────────────────┐
                        │   Google Drive       │
                        │   (Shared Drive)     │
                        │   - Folders by type  │
                        │   - Google Docs      │
                        └──────────────────────┘
```

## Requirements

| Component | Purpose | Installation |
|-----------|---------|--------------|
| macOS 15+ | Operating system | - |
| OBS Studio | Video/audio recording | `brew install --cask obs` |
| obs-cmd | CLI control for OBS | **Not on Homebrew** — download the release binary for your architecture from [grigio/obs-cmd](https://github.com/grigio/obs-cmd/releases) (e.g. `obs-cmd-x64-macos.tar.gz` for Intel, `obs-cmd-arm64-macos.tar.gz` for Apple Silicon), `chmod +x`, place on your `PATH` |
| SwiftBar | Menu bar plugin framework | `brew install --cask swiftbar` |
| Python 3.10+ | Runtime | conda, or pyenv + venv (see [Python Environment](USER_GUIDE.md#python-environment) — **Intel Macs**: PyTorch 2.2.2 is the last version published for Intel, which caps several other dependency versions; see the troubleshooting section if you hit segfaults or dependency conflicts) |
| WhisperX | Speech recognition | `pip install whisperx` |
| ffmpeg | Audio extraction | `brew install ffmpeg` |
| LLM API | Analysis (optional) — OpenAI or Anthropic | API key required, recommended via [1Password `op://` references](USER_GUIDE.md#secrets-management) rather than plaintext |

## Quick Start

```bash
# 1. Clone repository
git clone <repo-url>
cd call-analysis

# 2. Set up Python environment (conda shown here; pyenv + venv works equally
#    well — see USER_GUIDE.md#python-environment, especially if you're on
#    an Intel Mac, where conda's PyTorch build has known version conflicts)
conda create -n whisperx-recorder python=3.10
conda activate whisperx-recorder
pip install -r processing-pipeline/requirements.txt
pip install whisperx

# 3. Create configuration
cp processing-pipeline/config.default.json.template processing-pipeline/config.default.json
# Edit config.default.json with your credentials — or, better, with
# op://vault/item/field references resolved via the 1Password CLI at
# runtime; see USER_GUIDE.md#secrets-management

# 4. Create wrapper script (update PYTHON to match your env from step 2)
mkdir -p ~/.local/bin
cat > ~/.local/bin/whisperx-recorder << 'EOF'
#!/bin/bash
PYTHON="$HOME/anaconda3/envs/whisperx-recorder/bin/python"   # or .venv/bin/python3
SCRIPT="$HOME/path/to/call-analysis/processing-pipeline/whisperx_recorder.py"
exec "$PYTHON" "$SCRIPT" "$@"
EOF
chmod +x ~/.local/bin/whisperx-recorder

# 5. Install SwiftBar and point it at the plugin folder
brew install --cask swiftbar
mkdir -p ~/Documents/SwiftBarPlugins
ln -s "$(pwd)/SwiftBarPlugins/whisperx_recorder.1s.py" ~/Documents/SwiftBarPlugins/
# Launch SwiftBar once; on first run it may prompt you to choose a plugin
# folder — point it at ~/Documents/SwiftBarPlugins
```

**📖 See [USER_GUIDE.md](USER_GUIDE.md) for detailed setup and usage instructions.**

## Configuration

### Project Defaults (`config.default.json`)

```json
{
  "recording": {
    "output_dir": "~/OBSRecordings",
    "obs_ws_port": "4455",
    "obs_ws_password": "YOUR_PASSWORD",
    "keep_video": false
  },
  "transcription": {
    "diarize": false,
    "whisperx_path": "~/anaconda3/bin/whisperx",
    "hf_token": "YOUR_HUGGINGFACE_TOKEN"
  },
  "gdrive": {
    "enabled": false,
    "service_account_file": "your-service-account.json",
    "parent_folder_id": "YOUR_DRIVE_FOLDER_ID"
  },
  "llm": {
    "enabled": true,
    "auto_analyze": false,
    "provider": "openai",
    "api_key": "YOUR_OPENAI_API_KEY",
    "model": "gpt-4o",
    "anthropic_api_key": "YOUR_ANTHROPIC_API_KEY",
    "anthropic_model": "claude-sonnet-5"
  },
  "call_types": { ... }
}
```

`diarize` and `llm.auto_analyze` both default to `false` — the transcript is the deliverable by default; diarization and analysis are opt-in per recording (`--diarize`, `--keep-video`/`--delete-video`) or run later on demand (`whisperx-recorder analyze <folder> --call-type X`). `llm.provider` selects `openai` or `anthropic`; only one is active at a time.

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

Example call types included in the template:

| Type | Icon | Description |
|------|------|-------------|
| `team_meeting` | 👥 | General team meetings |
| `interview` | 👔 | Interview evaluation (with example context files) |
| `one_on_one` | 👤 | 1:1 meetings (prompts for person name) |
| `customer_meeting` | 🤝 | Customer calls (prompts for company name) |
| `project` | 🚀 | Project/initiative meetings |
| `generic` | 🎙️ | Default recording |

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
    └── analysis_<timestamp>_<model>.md   (if LLM analysis ran)
```

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

## License

MIT

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request
