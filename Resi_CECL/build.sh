#!/usr/bin/env bash
if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <path_to_venv>"
    exit 1
fi

VENV_PATH="$1"

if [ ! -d "$VENV_PATH" ]; then
    echo "Creating virtual environment at $VENV_PATH..."
    python3 -m venv "$VENV_PATH"
fi

source "$VENV_PATH/bin/activate"
echo "Building the project..."
# Add build steps here, e.g., install dependencies, run tests, etc.
deactivate
