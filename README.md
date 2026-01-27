# WhisperX Call Recording & Transcription

A macOS menu bar application for recording calls/meetings with OBS, transcribing them with WhisperX, and analyzing transcripts with ChatGPT.

## Features

- 🎙️ **One-click recording** via SwiftBar menu bar plugin
- 📝 **Automatic transcription** using WhisperX (OpenAI Whisper)
- 🎤 **Speaker diarization** (optional) - identifies who said what
- 🤖 **ChatGPT analysis** - AI-powered summaries with customizable prompts
- 📋 **Call type templates** - tailored prompts for interviews, 1:1s, team meetings
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
                        │  - ChatGPT Analysis  │
                        └──────────────────────┘
```

## Requirements

| Component | Purpose | Installation |
|-----------|---------|--------------|
| macOS 15+ | Operating system | - |
| OBS Studio | Video/audio recording | `brew install --cask obs` |
| obs-cmd | CLI control for OBS | `brew install obs-cmd` |
| SwiftBar | Menu bar plugin framework | `brew install swiftbar` |
| Python 3.10+ | Runtime | Anaconda/Miniconda |
| WhisperX | Speech recognition | `pip install whisperx` |
| ffmpeg | Audio extraction | `brew install ffmpeg` |
| OpenAI API | ChatGPT analysis (optional) | API key required |

## Quick Start

```bash
# 1. Clone repository
git clone <repo-url>
cd call-analysis

# 2. Set up Python environment
conda create -n whisperx-recorder python=3.10
conda activate whisperx-recorder
pip install -r processing-pipeline/requirements.txt

# 3. Create configuration
cp processing-pipeline/config.default.json.template processing-pipeline/config.default.json
# Edit config.default.json with your credentials

# 4. Create wrapper script
mkdir -p ~/.local/bin
cat > ~/.local/bin/whisperx-recorder << 'EOF'
#!/bin/bash
clear
PYTHON="$HOME/anaconda3/envs/whisperx-recorder/bin/python"
SCRIPT="$HOME/path/to/call-analysis/processing-pipeline/whisperx_recorder.py"
"$PYTHON" "$SCRIPT" "$@"
EOF
chmod +x ~/.local/bin/whisperx-recorder

# 5. Configure SwiftBar plugins folder → SwiftBarPlugins/
```

**📖 See [USER_GUIDE.md](USER_GUIDE.md) for detailed setup and usage instructions.**

## Configuration

### Project Defaults (`config.default.json`)

```json
{
  "recording": {
    "output_dir": "~/OBSRecordings",
    "obs_ws_port": "4455",
    "obs_ws_password": "YOUR_PASSWORD"
  },
  "transcription": {
    "diarize": true,
    "whisperx_path": "~/anaconda3/bin/whisperx",
    "hf_token": "YOUR_HUGGINGFACE_TOKEN"
  },
  "openai": {
    "api_key": "YOUR_OPENAI_API_KEY",
    "model": "gpt-4o",
    "enabled": true
  },
  "call_types": { ... }
}
```

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

Built-in call types with customized ChatGPT prompts:

| Type | Icon | Description |
|------|------|-------------|
| `team_meeting` | 👥 | General team meetings |
| `interview` | 👔 | Interview evaluation (with example context files) |
| `one_on_one` | 👤 | 1:1 meetings (prompts for person name) |
| `project` | 🚀 | Project/initiative meetings |
| `generic` | 🎙️ | Default recording |

Add custom call types in `config.default.json`. See [USER_GUIDE.md](USER_GUIDE.md#customizing-prompts) for details.

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
