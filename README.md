# WhisperX Call Recording & Transcription

A macOS menu bar application for recording calls/meetings with OBS, transcribing them using WhisperX, and analyzing transcripts with ChatGPT.

## Features

- 🎙️ **One-click recording** via SwiftBar menu bar plugin
- 📝 **Automatic transcription** using WhisperX (OpenAI Whisper)
- 🎤 **Speaker diarization** (optional) - identifies who said what
- 🤖 **ChatGPT analysis** - AI-powered meeting summaries and action items
- 📋 **Call type templates** - customized prompts for different meeting types
- ⏳ **Background processing** - start new recordings while previous ones transcribe
- 🔔 **macOS notifications** for recording status and completion
- 📁 **Organized output** - recordings organized by date and title

## Architecture

```
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────┐
│  SwiftBar Menu  │────▶│  whisperx_recorder   │────▶│     OBS     │
│     Plugin      │     │      (Python)        │     │  (via obs-cmd)
└─────────────────┘     └──────────────────────┘     └─────────────┘
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

- **macOS** (tested on macOS 15+)
- **OBS Studio** with WebSocket server enabled
- **obs-cmd** - CLI tool for OBS control (`brew install obs-cmd`)
- **SwiftBar** - Menu bar plugin framework (`brew install swiftbar`)
- **Python 3.10+** with Conda
- **WhisperX** - Speech recognition with word-level timestamps
- **ffmpeg** - Audio extraction (`brew install ffmpeg`)
- **OpenAI API key** (optional, for ChatGPT analysis)

## Installation

### 1. Clone the repository

```bash
git clone <repo-url>
cd call-analysis
```

### 2. Set up Python environment

```bash
conda create -n whisperx-recorder python=3.10
conda activate whisperx-recorder
pip install -r processing-pipeline/requirements.txt
```

### 3. Install WhisperX

```bash
# In base conda environment (or whisperx-recorder env)
pip install whisperx
```

### 4. Create wrapper script

```bash
mkdir -p ~/.local/bin
cat > ~/.local/bin/whisperx-recorder << 'EOF'
#!/bin/bash
clear
PYTHON="/path/to/anaconda3/envs/whisperx-recorder/bin/python"
SCRIPT="/path/to/call-analysis/processing-pipeline/whisperx_recorder.py"
"$PYTHON" "$SCRIPT" "$@"
sleep 1
osascript -e 'tell application "Terminal" to close front window' 2>/dev/null || true
EOF
chmod +x ~/.local/bin/whisperx-recorder
```

### 5. Configure SwiftBar

1. Install SwiftBar: `brew install swiftbar`
2. Set SwiftBar plugins folder to `SwiftBarPlugins/`
3. The plugin will appear as 🎙️ in your menu bar

### 6. Configure OBS

1. Enable WebSocket server in OBS (Tools → WebSocket Server Settings)
2. Note the port (default: 4455) and password
3. Update `config.default.json` or user settings if different

## Configuration

### Default Configuration

1. Copy the template to create your config:
   ```bash
   cp processing-pipeline/config.default.json.template processing-pipeline/config.default.json
   ```

2. Edit `config.default.json` with your values:
   ```json
   {
     "recording": {
       "output_dir": "~/OBSRecordings",
       "obs_ws_port": "4455",
       "obs_ws_password": "YOUR_OBS_WEBSOCKET_PASSWORD"
     },
     "transcription": {
       "diarize": true,
       "language": "en",
       "whisperx_path": "~/anaconda3/bin/whisperx",
       "hf_token": "YOUR_HUGGINGFACE_TOKEN"
     },
     "openai": {
       "api_key": "YOUR_OPENAI_API_KEY",
       "model": "gpt-4o",
       "enabled": true
     }
   }
   ```

> **Note:** `config.default.json` is gitignored to protect your secrets.

### User Overrides

Personal settings go in `~/.config/whisperx/settings.json`:

```json
{
  "transcription": {
    "diarize": false
  }
}
```

User settings override project defaults (deep merge).

## Call Types

The system supports customized ChatGPT prompts for different meeting types:

| Call Type | Icon | Description |
|-----------|------|-------------|
| Team Meeting | 👥 | General team meetings |
| Interview - SA | 🎯 | Solutions Architect interviews |
| 1:1 | 👤 | One-on-one meetings (prompts for person name) |
| Pipeline Council | 📊 | Sales pipeline reviews |
| EE XTeam Leader | 🌟 | Cross-team leadership calls |
| EE FE Leader | ⚡ | Field Engineering leadership |
| Sales Team | 💼 | Sales team meetings |
| Initiative Project | 🚀 | Project/initiative meetings |
| Recording | 🎙️ | Generic recording (default) |

Each call type has a tailored prompt that instructs ChatGPT what to extract from the transcript.

### Customizing Call Types

Edit the `call_types` section in `config.default.json` to add or modify call types:

```json
{
  "call_types": {
    "my_custom_type": {
      "name": "My Custom Meeting",
      "icon": "📌",
      "prompt": "You are analyzing a custom meeting. Please provide:\n1. **Summary**\n2. **Action Items**"
    }
  }
}
```

For meetings that require a person's name (like 1:1s), use `prompt_template` with `{person_name}`:

```json
{
  "one_on_one": {
    "name": "1:1",
    "icon": "👤",
    "prompt_template": "Analyzing 1:1 with {person_name}...",
    "requires_person_name": true
  }
}
```

## Usage

### Menu Bar Controls

| Icon | Status |
|------|--------|
| 🎙️ Ready •🤖 | Idle, diarization ON, ChatGPT enabled |
| 🎙️ Ready ○ | Idle, diarization OFF |
| 🔴 Meeting | Recording in progress |
| ⏳ Call | Processing transcription |
| ⏳ 2 Processing | Multiple jobs in queue |

### Quick Start by Call Type

Click menu bar icon and select from **Quick Start by Call Type**:
- **👥 Team Meeting** - Start with team meeting analysis prompt
- **🎯 Interview - SA** - Start with interview analysis prompt
- **👤 1:1** - Prompts for person name, then starts recording
- etc.

### Interactive Start

Select **▶️ Start Recording (interactive)** to:
1. Select call type from a numbered menu
2. Enter custom title (or use default)
3. For 1:1s, enter the person's name

### Stop Recording

Click **⏹️ Stop Recording** - processing starts automatically:
1. Audio extraction
2. WhisperX transcription
3. ChatGPT analysis (if enabled)

### Toggle Diarization

- **Speaker Diarization: ✓ On** - Identifies speakers (requires internet, slower)
- **Speaker Diarization: ✗ Off** - Faster, works offline

## CLI Usage

```bash
# Interactive start (select call type)
whisperx-recorder start

# Start with specific call type
whisperx-recorder start "Weekly Sync" --call-type team_meeting

# Start 1:1 with person name
whisperx-recorder start "1:1 - John" --call-type one_on_one --person John

# Start without diarization
whisperx-recorder start "Quick Call" --no-diarize

# Stop recording
whisperx-recorder stop

# Process existing video file with call type
whisperx-recorder process ~/Videos/interview.mov --call-type interview_sa

# List available call types
whisperx-recorder types

# Check status
whisperx-recorder status

# Configure diarization default
whisperx-recorder config diarize off
```

## Output Structure

```
~/OBSRecordings/
└── 2026-01-16_Weekly_Standup/
    ├── 2026-01-16_Weekly_Standup_143022.wav
    ├── 2026-01-16_Weekly_Standup_143022_metadata.json
    ├── 2026-01-16_Weekly_Standup_143022_transcript/
    │   ├── 2026-01-16_Weekly_Standup_143022.json
    │   ├── 2026-01-16_Weekly_Standup_143022.srt
    │   ├── 2026-01-16_Weekly_Standup_143022.tsv
    │   ├── 2026-01-16_Weekly_Standup_143022.txt
    │   └── 2026-01-16_Weekly_Standup_143022.vtt
    └── chatgpt_analysis.md                          # ChatGPT analysis output
```

### ChatGPT Analysis Output

The `chatgpt_analysis.md` file contains:
- Meeting metadata (title, type, timestamp, model used)
- AI-generated analysis based on the call type prompt
- For 1:1s, includes the person's name in context

## File Structure

```
call-analysis/
├── README.md
├── .gitignore
├── SwiftBarPlugins/
│   └── whisperx_recorder.1s.py       # Menu bar plugin
└── processing-pipeline/
    ├── config.default.json.template  # Config template (copy & fill in)
    ├── config.default.json           # Your config (gitignored)
    ├── requirements.txt              # Python dependencies
    ├── whisperx_recorder.py          # Main backend script
    ├── whisperx_action.sh            # Legacy shell script
    └── whisperx.1m.sh                # Legacy SwiftBar script
```

## State Files

Located in `~/.config/whisperx/`:

| File | Purpose |
|------|---------|
| `settings.json` | User configuration overrides |
| `recording_state.json` | Current recording session |
| `processing_state.json` | Background processing queue |

## Troubleshooting

### OBS not responding
- Ensure OBS WebSocket server is enabled
- Check port and password in config match OBS settings
- Verify `obs-cmd` is installed: `which obs-cmd`

### WhisperX not found
- Verify path in `config.default.json` → `transcription.whisperx_path`
- Check WhisperX is installed: `which whisperx`

### Diarization timeout
- Requires internet connection to download speaker models from HuggingFace
- Disable diarization for offline use: `whisperx-recorder config diarize off`

### ChatGPT analysis not running
- Verify `openai.enabled` is `true` in config
- Check `openai.api_key` is set correctly
- Ensure `openai` package is installed: `pip install openai`

### Terminal windows not closing
- Ensure wrapper script at `~/.local/bin/whisperx-recorder` has the auto-close code

## License

MIT

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request
