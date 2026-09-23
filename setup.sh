#!/bin/bash
# Call Analysis - Setup Script
#
# Automates the "Quick Start" steps from README.md: Python environment,
# obs-cmd, the whisperx-recorder wrapper, and the SwiftBar plugin folder.
# Safe to re-run — each step is idempotent.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PIPELINE_DIR="$SCRIPT_DIR/processing-pipeline"
VENV_DIR="$PIPELINE_DIR/.venv"
BIN_DIR="$HOME/.local/bin"
SWIFTBAR_PLUGINS_DIR="$HOME/Documents/SwiftBarPlugins"

echo "========================================"
echo "  Call Analysis Setup"
echo "========================================"
echo ""
echo "Repo: $SCRIPT_DIR"
echo ""

mkdir -p "$BIN_DIR"

# --- 1. Python environment (pyenv + venv) -----------------------------
echo "--- Python environment ---"
PY_VERSION="$(cat "$PIPELINE_DIR/.python-version" 2>/dev/null || echo "3.10.14")"

if [ -d "$VENV_DIR" ]; then
    echo "  venv already exists at $VENV_DIR, skipping creation"
else
    if command -v pyenv &> /dev/null; then
        echo "  Installing Python $PY_VERSION via pyenv (skips if already installed)..."
        pyenv install -s "$PY_VERSION"
        PYENV_ROOT="$(pyenv root)"
        PYTHON_BIN="$PYENV_ROOT/versions/$PY_VERSION/bin/python3"
    else
        echo "  pyenv not found — falling back to system python3 (expects 3.10+)"
        PYTHON_BIN="$(command -v python3)"
    fi
    echo "  Creating venv at $VENV_DIR..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

echo "  Installing dependencies (requirements.txt + whisperx)..."
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install -r "$PIPELINE_DIR/requirements.txt" --quiet
"$VENV_DIR/bin/pip" install whisperx --quiet
echo "  Done: $VENV_DIR/bin/whisperx"
echo ""

# --- 2. obs-cmd ---------------------------------------------------------
echo "--- obs-cmd ---"
if command -v obs-cmd &> /dev/null; then
    echo "  Already on PATH: $(command -v obs-cmd)"
elif [ -x "$BIN_DIR/obs-cmd" ]; then
    echo "  Already installed at $BIN_DIR/obs-cmd"
else
    ARCH="$(uname -m)"
    case "$ARCH" in
        arm64)  ASSET="obs-cmd-arm64-macos.tar.gz" ;;
        x86_64) ASSET="obs-cmd-x64-macos.tar.gz" ;;
        *) echo "  Unsupported architecture $ARCH — install obs-cmd by hand from https://github.com/grigio/obs-cmd/releases"; ASSET="" ;;
    esac

    if [ -n "$ASSET" ]; then
        echo "  Fetching latest obs-cmd release ($ASSET)..."
        API_JSON="$(curl -fsSL https://api.github.com/repos/grigio/obs-cmd/releases/latest)"
        DL_URL="$(echo "$API_JSON" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for a in data['assets']:
    if a['name'] == '$ASSET':
        print(a['browser_download_url'])
        break
")"
        SHA_URL="$(echo "$API_JSON" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for a in data['assets']:
    if a['name'] == '$ASSET.sha256':
        print(a['browser_download_url'])
        break
")"

        TMP_DIR="$(mktemp -d)"
        curl -fsSL "$DL_URL" -o "$TMP_DIR/$ASSET"
        if [ -n "$SHA_URL" ]; then
            curl -fsSL "$SHA_URL" -o "$TMP_DIR/$ASSET.sha256"
            (cd "$TMP_DIR" && shasum -a 256 -c "$ASSET.sha256")
        fi
        tar -xzf "$TMP_DIR/$ASSET" -C "$TMP_DIR"
        install -m 755 "$TMP_DIR/obs-cmd" "$BIN_DIR/obs-cmd"
        xattr -d com.apple.quarantine "$BIN_DIR/obs-cmd" 2>/dev/null || true
        rm -rf "$TMP_DIR"
        echo "  Installed to $BIN_DIR/obs-cmd ($("$BIN_DIR/obs-cmd" --version))"
    fi
fi
echo ""

# --- 3. Configuration ----------------------------------------------------
echo "--- Configuration ---"
CONFIG_FILE="$PIPELINE_DIR/config.default.json"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "  Creating config.default.json from template — edit it with your credentials"
    cp "$PIPELINE_DIR/config.default.json.template" "$CONFIG_FILE"
fi

echo "  Pointing transcription.whisperx_path at $VENV_DIR/bin/whisperx"
python3 << EOF
import json

config_file = "$CONFIG_FILE"
whisperx_path = "$VENV_DIR/bin/whisperx"

with open(config_file, "r") as f:
    config = json.load(f)

config.setdefault("transcription", {})["whisperx_path"] = whisperx_path

with open(config_file, "w") as f:
    json.dump(config, f, indent=2)
    f.write("\n")
EOF
echo ""

# --- 4. whisperx-recorder wrapper ----------------------------------------
echo "--- whisperx-recorder wrapper ---"
cat > "$BIN_DIR/whisperx-recorder" << EOF
#!/bin/bash
PYTHON="$VENV_DIR/bin/python3"
SCRIPT="$PIPELINE_DIR/whisperx_recorder.py"
exec "\$PYTHON" "\$SCRIPT" "\$@"
EOF
chmod +x "$BIN_DIR/whisperx-recorder"
echo "  Installed to $BIN_DIR/whisperx-recorder"
echo ""

# --- 5. SwiftBar plugin folder --------------------------------------------
echo "--- SwiftBar plugin ---"
mkdir -p "$SWIFTBAR_PLUGINS_DIR"
ln -sf "$SCRIPT_DIR/SwiftBarPlugins/whisperx_recorder.1s.py" "$SWIFTBAR_PLUGINS_DIR/"
echo "  Symlinked into $SWIFTBAR_PLUGINS_DIR"

CURRENT_PLUGIN_PATH="$(defaults read com.ameba.SwiftBar swiftBarPluginPath 2>/dev/null || true)"
if [ -z "$CURRENT_PLUGIN_PATH" ]; then
    defaults write com.ameba.SwiftBar swiftBarPluginPath -string "$SWIFTBAR_PLUGINS_DIR"
    echo "  Set SwiftBar's plugin folder to $SWIFTBAR_PLUGINS_DIR (restart SwiftBar to pick it up)"
elif [ "$CURRENT_PLUGIN_PATH" != "$SWIFTBAR_PLUGINS_DIR" ]; then
    echo "  SwiftBar's plugin folder is already set to a different path: $CURRENT_PLUGIN_PATH"
    echo "  Either move the symlink there, or change SwiftBar's plugin folder in its preferences."
else
    echo "  SwiftBar's plugin folder already matches"
fi
echo ""

echo "========================================"
echo "  Setup Complete"
echo "========================================"
echo ""
echo "Next steps:"
echo "  1. Make sure ~/.local/bin is on your PATH (it is, if you use these dotfiles)"
echo "  2. Edit $CONFIG_FILE with your OBS/HuggingFace/LLM credentials"
echo "     (or op:// references — see USER_GUIDE.md#secrets-management)"
echo "  3. For private/company prompts, clone call-analysis-prompts and run its setup.sh"
echo "  4. Verify: whisperx-recorder types"
echo "  5. Launch SwiftBar (or restart it) and confirm the menu bar item appears"
echo ""
