# WhisperX Recorder User Guide

Complete guide for installation, configuration, and daily usage.

---

## Table of Contents

1. [Installation](#installation)
2. [Configuration](#configuration)
3. [Menu Bar Usage](#menu-bar-usage)
4. [Command-Line Interface](#command-line-interface)
5. [Call Types](#call-types)
6. [Customizing Prompts](#customizing-prompts)
7. [Troubleshooting](#troubleshooting)

---

## Installation

### Prerequisites

Install required tools via Homebrew:

```bash
# Core tools
brew install ffmpeg obs-cmd swiftbar

# OBS Studio
brew install --cask obs
```

### Python Environment

```bash
# Create dedicated conda environment
conda create -n whisperx-recorder python=3.10
conda activate whisperx-recorder

# Install dependencies
cd /path/to/call-analysis
pip install -r processing-pipeline/requirements.txt
```

### Install WhisperX

WhisperX requires PyTorch. Install in your conda environment:

```bash
conda activate whisperx-recorder
pip install whisperx
```

> **Note:** WhisperX is CPU-intensive. First runs download models (~1-2GB).

### Create Wrapper Script

Create a wrapper script for easy CLI access:

```bash
mkdir -p ~/.local/bin

cat > ~/.local/bin/whisperx-recorder << 'EOF'
#!/bin/bash
clear
PYTHON="$HOME/anaconda3/envs/whisperx-recorder/bin/python"
SCRIPT="$HOME/Library/CloudStorage/OneDrive-Personal/Development/databricks/call-analysis/processing-pipeline/whisperx_recorder.py"

if [[ "$1" == "start" && -z "$2" ]]; then
    "$PYTHON" "$SCRIPT" "$@"
    sleep 1
    exit 0
else
    exec "$PYTHON" "$SCRIPT" "$@"
fi
EOF

chmod +x ~/.local/bin/whisperx-recorder
```

Add to your PATH if needed:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### Configure OBS

1. Open OBS Studio
2. Go to **Tools → WebSocket Server Settings**
3. Enable WebSocket server
4. Note the port (default: 4455) and set a password
5. Update your `config.default.json` with these values

### Configure SwiftBar

1. Open SwiftBar preferences
2. Set plugin folder to: `/path/to/call-analysis/SwiftBarPlugins`
3. The 🎙️ icon will appear in your menu bar

---

## Configuration

### Configuration Hierarchy

Settings are loaded in order (later overrides earlier):

1. **Hardcoded defaults** - Built into the script
2. **`config.default.json`** - Project-level configuration
3. **`~/.config/whisperx/settings.json`** - User overrides

### Initial Setup

```bash
# Copy template to create your config
cp processing-pipeline/config.default.json.template processing-pipeline/config.default.json

# Edit with your credentials
nano processing-pipeline/config.default.json
```

### Configuration Reference

```json
{
  "recording": {
    "output_dir": "~/OBSRecordings",      // Recording output directory
    "obs_ws_port": "4455",                 // OBS WebSocket port
    "obs_ws_password": "your_password"     // OBS WebSocket password
  },
  
  "transcription": {
    "diarize": true,                       // Enable speaker diarization
    "language": "en",                      // Transcription language
    "device": "cpu",                       // cpu or cuda
    "compute_type": "float32",             // float32 or float16
    "whisperx_path": "~/anaconda3/bin/whisperx",  // Path to whisperx
    "hf_token": "hf_xxx"                   // HuggingFace token for diarization
  },
  
  "openai": {
    "provider": "openai",                  // "openai" or "databricks"
    "enabled": true,                       // Enable/disable ChatGPT analysis
    
    "api_key": "sk-xxx",                   // OpenAI API key (when provider="openai")
    "model": "gpt-4o",                     // Model (when provider="openai")
    
    "databricks_profile": "my-profile",    // Databricks CLI profile (when provider="databricks")
    "databricks_model": "databricks-gpt-5-2"  // Model (when provider="databricks")
  },
  
  "call_types": {
    // Custom call type definitions (see Call Types section)
  }
}
```

### LLM Provider Configuration

The system supports two LLM backends for transcript analysis:

#### Option 1: Direct OpenAI

Use your personal OpenAI API key:

```json
{
  "openai": {
    "provider": "openai",
    "enabled": true,
    "api_key": "sk-proj-xxx",
    "model": "gpt-4o"
  }
}
```

#### Option 2: Databricks-Hosted Models

Use Databricks model serving endpoints with OAuth authentication. This keeps transcripts within your Databricks environment for security.

**Initial Setup:**

```bash
# Install Databricks SDK (if not already installed)
pip install databricks-sdk

# Configure Databricks CLI profile
databricks auth login --profile adb-2548836972759138

# Or use existing profile from ~/.databrickscfg
```

**Configuration:**

```json
{
  "openai": {
    "provider": "databricks",
    "enabled": true,
    "databricks_profile": "adb-2548836972759138",
    "databricks_model": "databricks-gpt-5-2"
  }
}
```

The Databricks SDK fetches OAuth tokens automatically from your configured profile. Tokens are refreshed as needed.

**Available Databricks Models:**
- `databricks-gpt-5-2` - GPT-5.2 hosted by Databricks
- `databricks-meta-llama-3-3-70b-instruct` - Llama 3.3 70B

### User Overrides

Create personal overrides that don't affect the project config:

```bash
mkdir -p ~/.config/whisperx
cat > ~/.config/whisperx/settings.json << 'EOF'
{
  "transcription": {
    "diarize": false
  }
}
EOF
```

---

## Menu Bar Usage

### Status Icons

| Icon | Meaning |
|------|---------|
| 🎙️ Ready •🤖 | Idle, diarization ON, ChatGPT enabled |
| 🎙️ Ready ○ | Idle, diarization OFF |
| 🔴 Recording | Recording in progress |
| ⏳ Processing | Transcription in progress |
| ⏳ 2 Processing | Multiple jobs in queue |

### Menu Options

#### Start Recording

**Quick Start by Call Type:**
- Click a call type to immediately start recording
- 1:1 option will prompt for person's name

**Interactive Start:**
- Opens terminal to select call type
- Allows custom title entry

#### Stop Recording

- Stops current recording
- Automatically starts background transcription
- You can immediately start a new recording

#### Toggle Diarization

- **✓ On** - Identifies speakers (requires internet)
- **✗ Off** - Faster, works offline

#### View Processing Jobs

When jobs are running, shows:
- Job title
- Call type
- Time started

---

## Command-Line Interface

### Commands

#### `start` - Start Recording

```bash
# Interactive mode (prompts for call type and title)
whisperx-recorder start

# With title only (uses generic call type)
whisperx-recorder start "Team Standup"

# With call type
whisperx-recorder start "Weekly Sync" --call-type team_meeting

# 1:1 with person name
whisperx-recorder start "1:1 - Sarah" --call-type one_on_one --person "Sarah"

# Without diarization
whisperx-recorder start "Quick Call" --no-diarize
```

#### `stop` - Stop Recording

```bash
whisperx-recorder stop
```

Stops recording and starts background transcription.

#### `process` - Process Existing Video

```bash
# Basic usage
whisperx-recorder process ~/Videos/meeting.mov

# With title
whisperx-recorder process ~/Videos/meeting.mov "Q1 Planning"

# With call type
whisperx-recorder process ~/Videos/interview.mov --call-type interview_fe_hm

# Full example
whisperx-recorder process ~/Videos/john_1on1.mov "1:1 - John" --call-type one_on_one --person "John" --no-diarize
```

Supported formats: `.mov`, `.mkv`, `.mp4`, `.avi`, `.webm`

#### `analyze` - Run ChatGPT Analysis

Re-run analysis on existing transcript:

```bash
# Basic (uses generic prompt)
whisperx-recorder analyze ~/OBSRecordings/2026-01-21_Meeting

# With specific call type
whisperx-recorder analyze ~/OBSRecordings/2026-01-21_Interview --call-type interview_fe_hm

# For 1:1 with person name
whisperx-recorder analyze ~/OBSRecordings/2026-01-21_1on1 --call-type one_on_one --person "Sarah"
```

#### `types` - List Call Types

```bash
whisperx-recorder types
```

Output:
```
Available Call Types:
==================================================
  👥 team_meeting        - Team Meeting 
  👔 interview_fe_hm     - Interview: FE Hiring Manager 
  🎯 interview_fe_panel  - Interview: FE Panel 
  👤 one_on_one          - 1:1 👤
  📊 pipeline_council    - Pipeline Council Call 
  🌟 ee_xteam_leader     - EE XTeam Leader Call 
  ⚡ ee_fe_leader        - EE FE Leader Call 
  💼 sales_team          - Sales Team Meeting 
  🚀 initiative_project  - Initiative Project Meeting 
  🎙️ generic             - Recording 

Use with: --call-type <type_id>
👤 = requires --person flag
```

#### `status` - Get Current Status

```bash
whisperx-recorder status
```

Returns JSON:
```json
{
  "recording": false,
  "processing": true,
  "processing_count": 1,
  "processing_jobs": [
    {
      "pid": 12345,
      "title": "Team Standup",
      "started_at": "2026-01-21T10:30:00",
      "call_type": "team_meeting"
    }
  ],
  "obs_running": false,
  "diarize_default": true,
  "openai_enabled": true
}
```

#### `config` - Configure Settings

```bash
# Enable diarization
whisperx-recorder config diarize on

# Disable diarization  
whisperx-recorder config diarize off
```

#### `logs` - View Logs

```bash
# Show last 50 log entries (default)
whisperx-recorder logs

# Show last 100 entries
whisperx-recorder logs 100

# Show all logs
whisperx-recorder logs 9999
```

#### `logs-clear` - Clear Logs

```bash
whisperx-recorder logs-clear
```

### Command-Line Flags

| Flag | Description |
|------|-------------|
| `--no-diarize` | Skip speaker diarization (faster, offline) |
| `--diarize` | Enable speaker diarization |
| `--call-type <type>` | Specify call type ID |
| `--person <name>` | Person name for 1:1 meetings |

### Examples

```bash
# Record a team meeting
whisperx-recorder start "Sprint Planning" --call-type team_meeting

# Record a hiring manager interview
whisperx-recorder start "Candidate X - HM" --call-type interview_fe_hm

# Record a 1:1 with John
whisperx-recorder start "Weekly 1:1" --call-type one_on_one --person "John"

# Quick recording without diarization
whisperx-recorder start "Quick Note" --no-diarize

# Process old video as panel interview
whisperx-recorder process ~/Downloads/panel_recording.mov --call-type interview_fe_panel

# Re-analyze with different call type
whisperx-recorder analyze ~/OBSRecordings/2026-01-21_Meeting --call-type pipeline_council
```

---

## Call Types

### Built-in Call Types

| ID | Name | Use Case |
|----|------|----------|
| `team_meeting` | Team Meeting | General team syncs, standups |
| `interview_fe_hm` | Interview: FE Hiring Manager | Hiring manager interviews (loads evaluation context) |
| `interview_fe_panel` | Interview: FE Panel | Panel presentation interviews (loads evaluation context) |
| `one_on_one` | 1:1 | One-on-one meetings (requires `--person`) |
| `pipeline_council` | Pipeline Council Call | Sales pipeline reviews |
| `ee_xteam_leader` | EE XTeam Leader Call | Cross-team leadership |
| `ee_fe_leader` | EE FE Leader Call | FE leadership meetings |
| `sales_team` | Sales Team Meeting | Sales team syncs |
| `initiative_project` | Initiative Project | Project/initiative meetings |
| `generic` | Recording | Default, general summary |

### Interview Call Types

The `interview_fe_hm` and `interview_fe_panel` call types load additional context files:

**Hiring Manager (`interview_fe_hm`):**
- `Agent_context/fe_interview_context_shared.md` - Role framework, levels, values
- `Agent_context/fe_interview_context_hiring_manager.md` - HM-specific signals
- `Agent_context/fe_interview_context_greenhouse.md` - Question handling
- `Agent_context/fe_interview_greenhouse_question_sets.md` - Exact Greenhouse questions

**Panel (`interview_fe_panel`):**
- `Agent_context/fe_interview_context_shared.md` - Role framework, levels, values
- `Agent_context/fe_interview_context_panel_presentation_demo.md` - Panel-specific signals
- `Agent_context/fe_interview_context_greenhouse.md` - Question handling
- `Agent_context/fe_interview_greenhouse_question_sets.md` - Exact Greenhouse questions

---

## Customizing Prompts

### Adding a New Call Type

Edit `config.default.json`:

```json
{
  "call_types": {
    "customer_call": {
      "name": "Customer Call",
      "icon": "🤝",
      "prompt": "You are analyzing a customer call. Please provide:\n1. **Customer Name & Context**\n2. **Issues Discussed**\n3. **Commitments Made**\n4. **Follow-up Actions**\n5. **Risk Flags**"
    }
  }
}
```

### Using Template Variables

For call types requiring dynamic input (like person names):

```json
{
  "manager_checkin": {
    "name": "Manager Check-in",
    "icon": "👔",
    "prompt_template": "You are analyzing a check-in with manager {person_name}. Focus on:\n1. **Feedback received**\n2. **Goals discussed**\n3. **Career development**",
    "requires_person_name": true
  }
}
```

### Using External Context Files

For complex prompts, use external markdown files:

```json
{
  "complex_interview": {
    "name": "Complex Interview",
    "icon": "📋",
    "context_files": [
      "Agent_context/my_shared_context.md",
      "Agent_context/my_interview_rubric.md"
    ],
    "prompt": "Based on the context provided, evaluate this candidate..."
  }
}
```

Context files are loaded from the repository root and concatenated before the prompt.

---

## Troubleshooting

### OBS Issues

**OBS not responding:**
```bash
# Check if OBS is running
pgrep -x obs

# Verify obs-cmd is installed
which obs-cmd

# Test obs-cmd connection
obs-cmd --websocket obsws://127.0.0.1:4455/YOUR_PASSWORD info
```

**WebSocket connection failed:**
- Ensure OBS WebSocket server is enabled (Tools → WebSocket Server Settings)
- Verify port and password match config

### Transcription Issues

**WhisperX not found:**
```bash
# Check WhisperX installation
which whisperx

# Or check full path
ls ~/anaconda3/bin/whisperx

# Update path in config if different
```

**Diarization timeout:**
- Diarization requires downloading HuggingFace models (~1GB)
- Requires active internet connection
- Disable for offline use: `whisperx-recorder config diarize off`

**Slow transcription:**
- CPU transcription is slow (10-30min for 1hr recording)
- Consider GPU if available
- Disable diarization for faster processing

### ChatGPT / LLM Issues

**Analysis not running:**
```bash
# Check config
cat ~/.config/whisperx/settings.json

# Verify OpenAI is enabled in config.default.json
grep -A6 '"openai"' processing-pipeline/config.default.json
```

**API errors:**
```bash
# Check logs for detailed errors
whisperx-recorder logs 100
```

### Databricks-Specific Issues

**"Databricks auth failed" error:**
```bash
# Re-authenticate with Databricks CLI
databricks auth login --profile YOUR_PROFILE_NAME

# Verify profile exists
cat ~/.databrickscfg

# Test connection
databricks auth token --profile YOUR_PROFILE_NAME
```

**Token expired:**
- Databricks OAuth tokens expire periodically
- Run `databricks auth login --profile <profile>` to refresh
- The SDK handles automatic refresh for valid sessions

**Wrong model name:**
- Check available models in your Databricks workspace
- Model names use format: `databricks-<model-name>`
- Common models: `databricks-gpt-5-2`, `databricks-meta-llama-3-3-70b-instruct`

**SDK not installed:**
```bash
pip install databricks-sdk
```

Common issues:
- Invalid API key
- Rate limiting (429 errors) - wait and retry
- Billing not set up on OpenAI account

### Terminal Issues

**Terminal windows not closing:**

Ensure wrapper script has auto-close logic:
```bash
cat ~/.local/bin/whisperx-recorder
```

Should contain `sleep 1` and `exit 0` for interactive starts.

**Long commands visible:**

Add `clear` at the start of wrapper script.

### View Debug Logs

```bash
# Recent logs
whisperx-recorder logs

# More logs
whisperx-recorder logs 200

# Full log file location
cat ~/.config/whisperx/logs/whisperx_recorder.log
```

### Reset State

If something gets stuck:

```bash
# Clear recording state
rm ~/.config/whisperx/recording_state.json

# Clear processing state
rm ~/.config/whisperx/processing_state.json

# Clear logs
whisperx-recorder logs-clear
```

---

## Quick Reference

### Most Common Commands

```bash
# Start team meeting recording
whisperx-recorder start "Team Standup" --call-type team_meeting

# Stop recording
whisperx-recorder stop

# Check status
whisperx-recorder status

# View logs
whisperx-recorder logs
```

### File Locations

| Location | Purpose |
|----------|---------|
| `~/OBSRecordings/` | Recording output |
| `~/.config/whisperx/` | State and settings |
| `~/.config/whisperx/logs/` | Debug logs |
| `~/.local/bin/whisperx-recorder` | Wrapper script |
