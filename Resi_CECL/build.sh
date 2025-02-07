#!/usr/bin/env bash

# Create temporary directory for virtual environment
VENV_TMP_DIR=$(mktemp -d)
echo "Creating virtual environment in temporary directory: $VENV_TMP_DIR"
python3 -m venv "$VENV_TMP_DIR/venv"
source "$VENV_TMP_DIR/venv/bin/activate"

# Create temporary directory for uv installation
UV_TMP_DIR=$(mktemp -d)
echo "Installing uv in temporary directory: $UV_TMP_DIR"
pip install --target="$UV_TMP_DIR" uv
export PYTHONPATH="$UV_TMP_DIR:$PYTHONPATH"

# Install requirements using uv
echo "Installing requirements using uv..."
uv pip install -r requirements.txt

echo "Building the project..."
# BEGIN PYINSTALLER
echo "Building executable for task 1 - task1"
pyinstaller --onefile --workpath=$(mktemp -d) --distpath=$(pwd)/dist "$(pwd)/1_task1/task1.py"

# END PYINSTALLER

# Cleanup
deactivate
rm -rf "$VENV_TMP_DIR"
rm -rf "$UV_TMP_DIR"
