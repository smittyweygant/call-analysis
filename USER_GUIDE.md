# WhisperX Recorder User Guide

Complete guide for installation, configuration, and daily usage.

---

## Table of Contents

1. [Installation](#installation)
2. [Configuration](#configuration)
3. [Google Drive Integration](#google-drive-integration)
4. [Menu Bar Usage](#menu-bar-usage)
5. [Command-Line Interface](#command-line-interface)
6. [Call Types](#call-types)
7. [Customizing Prompts](#customizing-prompts)
8. [Troubleshooting](#troubleshooting)

---

## Installation

### Automated setup

```bash
brew install --cask obs swiftbar
./setup.sh
```

`setup.sh` (repo root) installs obs-cmd, creates the pyenv+venv Python environment, writes `~/.local/bin/whisperx-recorder`, and points SwiftBar at `~/Documents/SwiftBarPlugins`. It's idempotent — re-run it any time (e.g. after a repo update) to pick up dependency changes. It doesn't touch `config.default.json` beyond creating it from the template if missing and keeping `transcription.whisperx_path` in sync — your credentials are untouched.

If you use conda instead of pyenv, or want to understand/customize what each step does, see the manual steps below.

### Manual setup

#### Prerequisites

Install required tools via Homebrew:

```bash
# Core tools
brew install ffmpeg swiftbar

# obs-cmd is NOT on Homebrew, despite some older docs suggesting `brew install obs-cmd`.
# Download the release binary for your Mac's architecture instead:
#   https://github.com/grigio/obs-cmd/releases
#   - Intel:         obs-cmd-x64-macos.tar.gz
#   - Apple Silicon: obs-cmd-arm64-macos.tar.gz
curl -L <release-url> | tar xz
chmod +x obs-cmd
mv obs-cmd /usr/local/bin/   # or ~/.local/bin if that's on your PATH

# OBS Studio
brew install --cask obs
```

#### Python Environment

Either pyenv + venv or conda works. Default to pyenv + venv (lighter, no separate package manager); pick conda only if you already use it for other projects.

**pyenv + venv (default):**

```bash
cd /path/to/call-analysis/processing-pipeline
pyenv local 3.10.14   # any 3.10+; reuse an existing version if you have one
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install whisperx
```

**conda (alternative):**

```bash
conda create -n whisperx-recorder python=3.10
conda activate whisperx-recorder
cd /path/to/call-analysis
pip install -r processing-pipeline/requirements.txt
pip install whisperx
```

Either way, set `transcription.whisperx_path` in your config to the resulting `whisperx` binary (e.g. `.../processing-pipeline/.venv/bin/whisperx` or `~/anaconda3/envs/whisperx-recorder/bin/whisperx`).

> **Note:** WhisperX is CPU-intensive. First runs download models (~1-2GB).

> **Intel Mac?** PyTorch 2.2.2 is the last version Apple published for Intel — this caps `numpy` (`<2`), which caps `scipy` (`<1.13`) and `transformers` (`4.44.x`-ish; newer `transformers` requires torch≥2.5 and silently breaks). You'll also need `matplotlib` installed explicitly (pyannote's VAD pipeline imports it but pip doesn't pull it in). If WhisperX segfaults (exit 139) or hangs mid-transcription, set `KMP_DUPLICATE_LIB_OK=TRUE` and `OMP_NUM_THREADS=1` before invoking it — multiple native libs (torch, ctranslate2, scipy) each bundle their own OpenMP runtime and collide on Intel Mac's dylib loading. This is already handled inside `run_whisperx()` in `whisperx_recorder.py`; only relevant if you're invoking WhisperX directly outside the app. See [Troubleshooting](#troubleshooting) if you hit this.

#### Create Wrapper Script

Create a wrapper script for easy CLI access:

```bash
mkdir -p ~/.local/bin

cat > ~/.local/bin/whisperx-recorder << 'EOF'
#!/bin/bash
PYTHON="/path/to/call-analysis/processing-pipeline/.venv/bin/python3"  # or ~/anaconda3/envs/whisperx-recorder/bin/python if you used conda
SCRIPT="/path/to/call-analysis/processing-pipeline/whisperx_recorder.py"  # UPDATE THIS PATH
exec "$PYTHON" "$SCRIPT" "$@"
EOF

chmod +x ~/.local/bin/whisperx-recorder
```

> **Important:** Update `PYTHON` and `SCRIPT` to match your environment (step above) and where you cloned the repository. SwiftBar invokes this wrapper directly (`bash=~/.local/bin/whisperx-recorder`), so both paths need to be absolute and correct — there's no shell profile/PATH to fall back on in that context.

Add to your PATH if needed:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

#### Configure OBS

1. Open OBS Studio
2. Go to **Tools → WebSocket Server Settings**
3. Enable WebSocket server
4. Note the port (default: 4455) and set a password
5. Update your `config.default.json` with these values

#### Configure SwiftBar

SwiftBar reads plugins from a folder you point it at. Rather than setting that folder directly to the repo (which would also pick up non-plugin files), symlink just the plugin file into SwiftBar's default folder — this keeps the plugin live-updated with any repo changes without a copy step:

```bash
mkdir -p ~/Documents/SwiftBarPlugins
ln -s "/path/to/call-analysis/SwiftBarPlugins/whisperx_recorder.1s.py" ~/Documents/SwiftBarPlugins/
```

1. Launch SwiftBar. On first run it opens a folder picker — choose `~/Documents/SwiftBarPlugins`. If you miss the dialog or it doesn't appear, quit SwiftBar and set the preference directly instead: `defaults write com.ameba.SwiftBar swiftBarPluginPath -string "$HOME/Documents/SwiftBarPlugins"`, then relaunch. (The preference key is `swiftBarPluginPath`, not the `PluginDirectory` this doc used to say — verified against the strings in SwiftBar's own binary.)
2. The 🎙️ icon should appear in your menu bar within a few seconds.

If the menu is empty or shows an error, the plugin's shebang (`#!/usr/bin/env python3`) needs to resolve to a Python 3 with no special dependencies — it only reads state/config files directly and shells out to the `whisperx-recorder` wrapper for actions, so the system Python is fine here even though the wrapper itself needs the WhisperX environment.

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
    "diarize": false,                      // Enable speaker diarization (opt-in; needs internet + HF token)
    "language": "en",                      // Transcription language
    "device": "cpu",                       // cpu or cuda
    "compute_type": "float32",             // float32 or float16 (see Troubleshooting before changing on CPU)
    "whisperx_path": "~/path/to/call-analysis/processing-pipeline/.venv/bin/whisperx",  // Path to whisperx
    "hf_token": "hf_xxx"                   // HuggingFace token for diarization
  },
  
  "llm": {
    "enabled": true,                       // Whether an LLM provider is configured at all
    "auto_analyze": false,                 // Whether analysis runs automatically after start/stop or process
    "provider": "openai",                  // "openai" or "anthropic" — one active at a time

    "api_key": "sk-xxx",                   // OpenAI API key (when provider="openai")
    "model": "gpt-4o",                     // Model (when provider="openai")

    "anthropic_api_key": "sk-ant-xxx",     // Anthropic API key (when provider="anthropic")
    "anthropic_model": "claude-sonnet-5"   // Model (when provider="anthropic")
  },
  
  "call_types": {
    // Custom call type definitions (see Call Types section)
  }
}
```

`auto_analyze: false` means `start`/`stop` and `process` produce a transcript only — analysis doesn't fire automatically. Run it on demand with `whisperx-recorder analyze <folder> --call-type X` whenever you actually want it (independent of `auto_analyze`, as long as `enabled` is true and the active provider has a key). Set `auto_analyze: true` if you want it to run every time instead.

### LLM Provider Configuration

The system supports two LLM backends for transcript analysis — pick one via `llm.provider`:

#### Option 1: Direct OpenAI

```json
{
  "llm": {
    "provider": "openai",
    "enabled": true,
    "api_key": "sk-proj-xxx",
    "model": "gpt-4o"
  }
}
```

#### Option 2: Anthropic

```json
{
  "llm": {
    "provider": "anthropic",
    "enabled": true,
    "anthropic_api_key": "sk-ant-xxx",
    "anthropic_model": "claude-sonnet-5"
  }
}
```

Both fields' values can be `op://vault/item/field` references instead of literal keys — see [Secrets Management](#secrets-management).

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

### Secrets Management

Any secret-shaped config value — `recording.obs_ws_password`, `transcription.hf_token`, `llm.api_key`, `llm.anthropic_api_key`, `gdrive.service_account_file` — can be either a literal string or an `op://vault/item/field` reference, resolved via the [1Password CLI](https://developer.1password.com/docs/cli/) at the point the value is actually used (not eagerly at startup, so commands like `types`/`status` that don't need secrets don't trigger 1Password prompts).

```json
{
  "llm": {
    "anthropic_api_key": "op://Development/Anthropic API Key/credential"
  }
}
```

Requires `op` installed and the 1Password desktop app signed in with CLI integration enabled (Settings → Developer). For a JSON-blob secret like a Google service-account key, minify it to one line and store it in a 1Password field rather than referencing a file path — `gdrive.service_account_file` accepts an `op://` reference the same way, resolved and parsed as JSON at connection time.

**Reducing repeated Touch ID prompts:** if you're invoking the CLI interactively often (e.g. via SwiftBar's "Start Recording (interactive)", which opens a new Terminal session each time), 1Password's default **Settings → Developer → "Ask approval for each new"** set to *application and terminal session* treats every new session as an unrecognized requester. Narrowing that to *application*, and setting **"Remember key approval"** to *"Until 1Password locks"* (or a fixed interval), significantly cuts prompt frequency without storing anything in plaintext.

## Google Drive Integration

Analysis files can be automatically uploaded to Google Drive as formatted Google Docs, into either a Google Workspace **Shared Drive** or a regular **folder** shared with the service account.

> **If you don't have Google Workspace:** a Shared Drive isn't available to you — a personal Gmail account can't create one, and there's no other interface or API workaround. Use a regular Drive folder instead (Setup below covers this). Be aware a bare service account with no Workspace backing has **zero Drive storage quota of its own**, so uploads can fail with `storageQuotaExceeded` even into a folder it's been granted Editor access to — the file is still attributed to the service account for quota purposes regardless of the target folder. If you hit this, the real fix is switching the auth flow from a service-account key to an OAuth user-consent flow (so uploads are owned by your own account and quota), which this app doesn't implement yet.

### Setup

**1. Create a Google Cloud Service Account:**

- Go to [Google Cloud Console](https://console.cloud.google.com/)
- Create a new project or use an existing one
- Enable the Google Drive API
- Create a Service Account and download the JSON key file
- Store it in 1Password rather than leaving the raw key file on disk (see [Secrets Management](#secrets-management)) — minify the JSON to one line and reference it via `gdrive.service_account_file: "op://vault/item/field"`

**2. Share a destination with the service account:**

- **Shared Drive** (Workspace only): create one, add the service account email (from the JSON file) as a "Content Manager"
- **Regular folder** (works on any account): create a folder in your own Drive, share it with the service account email as an Editor
- Either way, copy the ID from the URL: `https://drive.google.com/drive/folders/<ID>`

**3. Configure:**

```json
{
  "gdrive": {
    "enabled": true,
    "service_account_file": "op://Development/Google Service Account/credential",
    "parent_folder_id": "YOUR_FOLDER_OR_SHARED_DRIVE_ID"
  }
}
```

### Features

- **Auto-upload after analysis** - Analysis files upload automatically when processing completes
- **Folder organization** - Folders are auto-created per call type (e.g., "Customer Meeting", "Interview: FE Panel")
- **Formatted Google Docs** - Markdown is converted to HTML for proper formatting in Google Docs
- **Document naming** - Format: `<Call Type> <yy_mm_dd> - <title>`

### User Settings

Enable/disable in your `~/.config/whisperx/settings.json`:

```json
{
  "gdrive": {
    "enabled": true
  }
}
```

---

## Menu Bar Usage

### Status Icons

| Icon | Meaning |
|------|---------|
| 🎙️ Ready •🤖 | Idle, diarization ON, LLM auto-analyze ON |
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
whisperx-recorder process ~/Videos/interview.mov --call-type interview

# Full example
whisperx-recorder process ~/Videos/john_1on1.mov "1:1 - John" --call-type one_on_one --person "John" --no-diarize
```

Supported formats: `.mov`, `.mkv`, `.mp4`, `.avi`, `.webm`

#### `analyze` - Run LLM Analysis

Re-run analysis on existing transcript:

```bash
# Basic (uses generic prompt)
whisperx-recorder analyze ~/OBSRecordings/2026-01-21_Meeting

# With specific call type
whisperx-recorder analyze ~/OBSRecordings/2026-01-21_Interview --call-type interview

# For 1:1 with person name
whisperx-recorder analyze ~/OBSRecordings/2026-01-21_1on1 --call-type one_on_one --person "Sarah"
```

#### `types` - List Call Types

```bash
whisperx-recorder types
```

Output (example with default types):
```
Available Call Types:
==================================================
  👥 team_meeting        - Team Meeting 
  👔 interview           - Interview 
  👤 one_on_one          - 1:1 👤
  🚀 project             - Project Meeting 
  🎙️ generic             - Recording 

Use with: --call-type <type_id>
👤 = requires --person flag
```

> **Note:** Your actual list may include additional custom call types defined in your `config.default.json`.

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
  "diarize_default": false,
  "llm_enabled": true
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

# Record an interview (with context files)
whisperx-recorder start "Candidate Interview" --call-type interview

# Record a 1:1 with John
whisperx-recorder start "Weekly 1:1" --call-type one_on_one --person "John"

# Quick recording without diarization
whisperx-recorder start "Quick Note" --no-diarize

# Process an existing video
whisperx-recorder process ~/Downloads/meeting.mov --call-type team_meeting

# Re-analyze with different call type
whisperx-recorder analyze ~/OBSRecordings/2026-01-21_Meeting --call-type project
```

---

## Call Types

### Example Call Types (from template)

| ID | Name | Use Case |
|----|------|----------|
| `team_meeting` | Team Meeting | General team syncs, standups |
| `interview` | Interview | Candidate interviews (demonstrates context files) |
| `one_on_one` | 1:1 | One-on-one meetings (requires `--person`) |
| `customer_meeting` | Customer Meeting | Customer calls (prompts for company name) |
| `project` | Project Meeting | Project/initiative meetings |
| `generic` | Recording | Default, general summary |

These are examples from `config.default.json.template`. Add your own custom call types as needed.

### Call Types with Context Files

The `interview` call type demonstrates loading external context files. These files provide additional information to the AI for more tailored analysis:

```json
{
  "interview": {
    "name": "Interview",
    "icon": "👔",
    "context_files": [
      "examples/context/interview_shared_context.md",
      "examples/context/interview_rubric.md"
    ],
    "prompt": "Evaluate using the provided context..."
  }
}
```

See the `examples/` folder for sample context files you can customize.

---

## Customizing Prompts

### Adding a New Call Type

Edit `config.default.json`:

```json
{
  "call_types": {
    "sales_call": {
      "name": "Sales Call",
      "icon": "💰",
      "prompt": "You are analyzing a sales call. Please provide:\n1. **Opportunity Overview**\n2. **Customer Pain Points**\n3. **Competitive Mentions**\n4. **Next Steps**\n5. **Deal Risk Assessment**"
    }
  }
}
```

### Using Template Variables

For call types requiring dynamic input (like person or company names):

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

### Custom Input Prompts

Customize what the user is asked to enter with `name_prompt`:

```json
{
  "customer_call": {
    "name": "Customer Call",
    "icon": "🤝",
    "prompt_template": "Analyzing call with {person_name}...",
    "requires_person_name": true,
    "name_prompt": "Enter customer/company name"
  }
}
```

### Using External Prompt Files

For complex prompts, load from external markdown files using `prompt_file`:

```json
{
  "complex_interview": {
    "name": "Complex Interview",
    "icon": "📋",
    "context_files": [
      "Agent_context/interview_context.md",
      "Agent_context/interview_rubric.pdf"
    ],
    "prompt_file": "Agent_prompts/interview_evaluation_prompt.md"
  }
}
```

The prompt file is loaded from `context_base_path` and supports `{person_name}` substitution.

**Benefits of external prompt files:**
- Version control prompts separately
- Easier to edit and review long prompts
- Share prompts across call types
- Keep config file clean and readable

### Example Prompt Files

The repository includes example files in the `examples/` folder to help you get started:

```
examples/
├── prompts/
│   └── interview_evaluation_prompt.md    # Sample interview evaluation prompt
└── context/
    ├── interview_shared_context.md       # Role requirements, evaluation criteria
    └── interview_rubric.md               # Scoring rubric and question framework
```

These examples demonstrate the structure and format for effective prompts. Copy and customize them for your specific needs.

### Using External Context Files

For complex prompts, use external markdown files that are loaded before the main prompt:

```json
{
  "complex_interview": {
    "name": "Complex Interview",
    "icon": "📋",
    "context_files": [
      "interview/shared_context.md",
      "interview/evaluation_rubric.md"
    ],
    "prompt": "Based on the context provided, evaluate this candidate..."
  }
}
```

Context files are loaded relative to `context_base_path` (defaults to repository root).

### Private Prompt Repositories

For sensitive or proprietary prompt content, you can maintain a separate private repository:

**1. Create a private GitHub repository for your prompts:**

```bash
# Create and clone your private prompts repo
git init ~/my-prompts
cd ~/my-prompts

# Copy examples as a starting point
cp -r /path/to/call-analysis/examples/* .

# Customize for your organization
# Edit context/interview_shared_context.md with your role requirements
# Edit context/interview_rubric.md with your evaluation criteria

# Commit and push to your private GitHub repo
git add .
git commit -m "Initial prompt setup"
git remote add origin git@github.com:youruser/my-prompts.git
git push -u origin main
```

**2. Configure the context base path in your user settings:**

Create or edit `~/.config/whisperx/settings.json`:

```json
{
  "context_base_path": "~/my-prompts"
}
```

**3. Reference files relative to that base path:**

In your `config.default.json` (which is gitignored):

```json
{
  "call_types": {
    "my_interview": {
      "name": "My Interview Type",
      "icon": "👔",
      "context_files": [
        "interview/shared_context.md",
        "interview/evaluation_rubric.md"
      ],
      "prompt": "Using the context above, evaluate the candidate..."
    }
  }
}
```

**Benefits of this approach:**

- **Keep main repo public** - Generic examples work without private content
- **Version control prompts separately** - Iterate on prompts independently
- **Easy team sharing** - Share private repo with teammates who need access
- **Graceful fallback** - Missing context files log warnings but don't fail

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

# Or check full path (pyenv+venv or conda, whichever you used)
ls /path/to/call-analysis/processing-pipeline/.venv/bin/whisperx
ls ~/anaconda3/envs/whisperx-recorder/bin/whisperx

# Update transcription.whisperx_path in config to match
```

**Diarization timeout:**
- Diarization requires downloading HuggingFace models (~1GB) and accepting their gated-model license on huggingface.co (`pyannote/speaker-diarization-3.1`, `pyannote/segmentation-3.0`) while logged in as the account tied to your `hf_token`
- Requires active internet connection
- Off by default; explicitly enable per-recording with `--diarize`, or set the default with `whisperx-recorder config diarize on`

**Slow transcription:**
- CPU transcription is slow (roughly real-time to 2x for plain transcription; diarization on a long recording can run considerably longer on CPU — budget accordingly)
- Consider GPU if available
- Diarization is off by default for exactly this reason; only enable it when you actually need speaker labels

**Segfault (exit 139) or hang mid-transcription, especially on Intel Mac:**
- Set `KMP_DUPLICATE_LIB_OK=TRUE` and `OMP_NUM_THREADS=1` before invoking `whisperx` — see the Intel Mac note under [Python Environment](#python-environment). Already handled inside the app's own `run_whisperx()`; only relevant if you're running the `whisperx` binary directly.

**`compute_type: int8`:** don't use it on this stack — it silently drops most of the transcript with no error on the torch/ctranslate2 versions this app is pinned to on Intel Mac (confirmed: dropped 3 of 4 segments on a test clip). Stick with `float32` despite the speed cost.

### LLM Analysis Issues

**Analysis not running:**
```bash
# Check config
cat ~/.config/whisperx/settings.json

# Verify the llm section in config.default.json
grep -A10 '"llm"' processing-pipeline/config.default.json
```

Remember `auto_analyze: false` (the default) means analysis never runs automatically — that's expected, not a bug. Run it explicitly: `whisperx-recorder analyze <folder> --call-type X`.

**API errors:**
```bash
# Check logs for detailed errors
whisperx-recorder logs 100
```

Common issues:
- Invalid or unresolved API key (if using an `op://` reference, confirm `op read <the-reference>` works standalone — see [Secrets Management](#secrets-management))
- Rate limiting (429 errors) - wait and retry
- Billing/quota not set up on the provider account
- Anthropic responses with no text content surface a specific error naming the model's `stop_reason` (e.g. a safety refusal) — check the logs for that rather than a generic failure

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
