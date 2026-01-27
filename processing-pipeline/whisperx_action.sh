#!/bin/bash
#
# WhisperX Recording & Transcription Script
# Records via OBS, extracts audio, and transcribes using WhisperX
#
# Usage: whisperx_action.sh [prefix]
#   prefix: Optional filename prefix. If not provided, prompts interactively.
#
# NOTE: For calendar integration and menu bar UI, use whisperx_recorder.py instead.
#

# ─── Configuration ────────────────────────────────────────────────────────────
OBS_RECORD_DIR="$HOME/OBSRecordings"  # Where OBS saves recordings (must match OBS settings)
export TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD="1"  # Required for WhisperX

# OBS WebSocket settings (must match OBS → Tools → WebSocket Server Settings)
OBS_WS_PORT="4455"
# OBS_WS_PASSWORD="yl996e7PNrN8P2oX"  # Set this if you enabled authentication in OBS
OBS_WS_PASSWORD="nbVaYq44miE57wSA"

# Hugging Face API token for WhisperX speaker diarization
HF_TOKEN="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"

# ─── Check for obs-cmd ────────────────────────────────────────────────────────
# Install: Download from https://github.com/grigio/obs-cmd/releases
#          or: cargo install obs-cmd
if ! command -v obs-cmd &> /dev/null; then
    echo "⚠️  obs-cmd not found. Install it for automatic recording control."
    echo "   Download from: https://github.com/grigio/obs-cmd/releases"
    echo "   Then: chmod +x obs-cmd && sudo mv obs-cmd /usr/local/bin/"
    echo ""
    echo "   Falling back to manual recording mode..."
    OBS_CMD_AVAILABLE=false
else
    OBS_CMD_AVAILABLE=true
    # Build obs-cmd connection string
    if [ -n "$OBS_WS_PASSWORD" ]; then
        # OBS_CMD_ARGS="-w ws://127.0.0.1:${OBS_WS_PORT} -p ${OBS_WS_PASSWORD}"
        OBS_CMD_ARGS="--websocket obsws://127.0.0.1:${OBS_WS_PORT}/${OBS_WS_PASSWORD}"
        echo $OBS_CMD_ARGS
    else
        OBS_CMD_ARGS="-w ws://127.0.0.1:${OBS_WS_PORT}"
        echo "Password is not set"
    fi
    export OBS_CMD_ARGS
fi

# ─── Get filename prefix (from argument or prompt) ────────────────────────────
if [ -n "$1" ]; then
    PREFIX="$1"
else
read -p "📝 Enter a filename prefix (e.g., meeting, interview): " PREFIX
fi
PREFIX=${PREFIX:-call}  # Default to 'call' if empty
PREFIX=$(echo "$PREFIX" | tr ' ' '_' | tr -cd '[:alnum:]_-')  # Sanitize input

# ─── Derived paths ────────────────────────────────────────────────────────────
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
FILENAME="${PREFIX}_$TIMESTAMP"
OUTPUT_DIR="$OBS_RECORD_DIR/$PREFIX"
TRANSCRIPT_DIR="$OUTPUT_DIR/${FILENAME}_transcript"
AUDIO_FILE="$OUTPUT_DIR/${PREFIX}_${TIMESTAMP}.wav"

# ─── Setup directories ────────────────────────────────────────────────────────
mkdir -p "$OUTPUT_DIR"
mkdir -p "$TRANSCRIPT_DIR"

# ─── Launch OBS and start recording ──────────────────────────────────────────
if ! pgrep -x "obs" > /dev/null; then
    echo "🚀 Launching OBS and starting recording..."
    open -a "OBS" --args --startrecording
    sleep 5
else
    echo "📹 OBS is already running."
    if [ "$OBS_CMD_AVAILABLE" = true ]; then
        echo "▶️  Starting recording via obs-cmd..."
        obs-cmd $OBS_CMD_ARGS recording start
        sleep 1
    else
        echo "📌 Please start recording manually in OBS."
        read -p "   Press Enter once recording has started..."
    fi
fi

# ─── Wait for recording to finish ─────────────────────────────────────────────
if [ "$OBS_CMD_AVAILABLE" = true ]; then
    echo ""
    echo "🎙️  Recording in progress..."
    read -p "⏹️  Press Enter to stop recording..."
    echo "⏹️  Stopping recording..."
    obs-cmd $OBS_CMD_ARGS recording stop
    sleep 2  # Give OBS time to finalize the file
else
    read -p "⏹️  Press Enter after you stop recording manually in OBS..."
fi

# ─── Process the recording ────────────────────────────────────────────────────
# Find the latest video file (supports mov, mkv, mp4)
LATEST=$(ls -t "$OBS_RECORD_DIR"/*.{mov,mkv,mp4} 2>/dev/null | head -n 1)

if [ -z "$LATEST" ] || [ ! -f "$LATEST" ]; then
    echo "❌ No video file found in $OBS_RECORD_DIR"
    echo "   Make sure OBS is configured to save recordings there."
    exit 1
fi

echo "📁 Found recording: $LATEST"

# Get the original extension and use it for the video file
EXTENSION="${LATEST##*.}"
VIDEO_FILE="$OUTPUT_DIR/$FILENAME.$EXTENSION"

mv "$LATEST" "$VIDEO_FILE"

if [ ! -f "$VIDEO_FILE" ]; then
    echo "❌ Failed to move video file to $VIDEO_FILE"
    exit 1
fi

echo "📦 Moved to: $VIDEO_FILE"

# ─── Close OBS ───────────────────────────────────────────────────────────────
echo "🛑 Closing OBS..."
osascript -e 'try' -e 'tell application "OBS" to quit' -e 'end try' 2>/dev/null

# ─── Extract audio ────────────────────────────────────────────────────────────
ffmpeg -i "$VIDEO_FILE" -ar 16000 -ac 1 "$AUDIO_FILE"

# Verify audio conversion succeeded, then delete the input video
if [ -f "$AUDIO_FILE" ] && [ -s "$AUDIO_FILE" ]; then
    echo "✅ Audio conversion successful. Deleting input video..."
    rm "$VIDEO_FILE"
else
    echo "❌ Audio conversion failed. Keeping input video for retry."
    exit 1
fi

# ─── Transcribe with WhisperX ─────────────────────────────────────────────────
# Add --diarize --hf_token "$HF_TOKEN" for speaker identification
whisperx "$AUDIO_FILE" \
  --language en \
  --compute_type float32 \
  --device cpu \
  --output_dir "$TRANSCRIPT_DIR" \
  --diarize \
  --hf_token "$HF_TOKEN"

# open "$TRANSCRIPT_DIR"


