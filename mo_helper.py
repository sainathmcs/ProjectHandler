#!/usr/bin/env python3
"""
model_organizer.py

This CLI tool initializes and maintains a model task project with a defined folder
structure and a YAML mapping (Mo.yaml). It supports operations such as add, delete,
and move. Before performing any operation, it validates the current YAML and folder
structure by building a doubly linked list of task groups. Folders not matching our naming
scheme are ignored.

File creation and folder creation are “safe” – if a file/folder exists, you will be asked
whether to overwrite it (default: no). In that case, the existing file/folder is backed up
to a temporary location (and the backup location is printed).

Usage examples:
  - Initialize a project:
      $ python model_organizer.py init --model "MyModel"
  - Validate current structure:
      $ python model_organizer.py validate
  - Add a sequential task (or insert in the middle):
      $ python model_organizer.py add --pos 2 --name task_new
  - Add a parallel task:
      $ python model_organizer.py add --pos 3a --name task_parallel
  - Delete a task (serial or parallel) by its full position:
      $ python model_organizer.py delete --pos 3b
  - Move a task from one position to another:
      $ python model_organizer.py move --from 3a --to 4
"""

import os
import re
import shutil
import subprocess
import tempfile
import click
import yaml

# =============================
# Template-loading functions
# =============================

def load_template(template_filename, default_content):
    """Try to load a template file from a 'templates' folder relative to this script."""
    template_path = os.path.join(os.path.dirname(__file__), "templates", template_filename)
    if os.path.exists(template_path):
        with open(template_path, "r") as f:
            return f.read()
    return default_content

DEFAULT_REQ_TEMPLATE = "pyinstaller\n"
DEFAULT_WRAPPER_TEMPLATE = '''"""
Wrapper for task: {task_name}
"""
import sys
from {task_module} import main

def wrapper():
    # (Optional: add command-line argument parsing)
    main()

if __name__ == '__main__':
    wrapper()
'''
DEFAULT_TASK_TEMPLATE = '''"""
Skeleton for task: {task_name}
"""

def main():
    print("Running task {task_name}...")

if __name__ == '__main__':
    main()
'''
DEFAULT_BUILD_SH_TEMPLATE = """#!/usr/bin/env bash
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
"""
DEFAULT_TOX_CONFIG = """[tox]
envlist = py312

[testenv]
basepython = python3.12
deps =
    uv
commands =
    uv
"""

def get_requirements_template():
    return load_template("requirements.txt", DEFAULT_REQ_TEMPLATE)

def get_wrapper_template(task_name):
    # Replace placeholders: task_name and task_module (assumed to be the same as task_name)
    return load_template("wrapper_template.py", DEFAULT_WRAPPER_TEMPLATE).format(
        task_name=task_name, task_module=task_name
    )

def get_task_template(task_name):
    return load_template("task_template.py", DEFAULT_TASK_TEMPLATE).format(task_name=task_name)

def get_build_sh_template():
    return load_template("build.sh", DEFAULT_BUILD_SH_TEMPLATE)

def get_tox_config_template():
    return load_template("tox.ini", DEFAULT_TOX_CONFIG)

# =============================
# Backup, Rename, and Safe Write Helpers
# =============================

def backup_path(path):
    """Back up a file or folder to a temporary directory and return the backup location."""
    backup_dir = tempfile.mkdtemp(prefix="model_organizer_backup_")
    base_name = os.path.basename(path)
    dest = os.path.join(backup_dir, base_name)
    if os.path.isfile(path):
        shutil.copy2(path, dest)
    elif os.path.isdir(path):
        shutil.copytree(path, dest)
    return backup_dir

def safe_write_file(file_path, content):
    """Write content to file_path. If file_path exists, ask whether to overwrite.
    If yes, back up the existing file first."""
    if os.path.exists(file_path):
        overwrite = click.confirm(f"File '{file_path}' exists. Overwrite?", default=False)
        if not overwrite:
            click.echo(f"Skipped writing to '{file_path}'.")
            return
        else:
            backup = backup_path(file_path)
            click.echo(f"Backed up '{file_path}' to '{backup}'.")
    with open(file_path, "w") as f:
        f.write(content)
    click.echo(f"Wrote file '{file_path}'.")

def safe_create_directory(dir_path):
    """Create a directory. If it exists, ask whether to overwrite it (i.e. delete and re-create).
    If yes, back up the existing folder first."""
    if os.path.exists(dir_path):
        overwrite = click.confirm(f"Directory '{dir_path}' exists. Overwrite?", default=False)
        if not overwrite:
            click.echo(f"Using existing directory '{dir_path}'.")
            return
        else:
            backup = backup_path(dir_path)
            click.echo(f"Backed up directory '{dir_path}' to '{backup}'.")
            shutil.rmtree(dir_path)
    os.makedirs(dir_path, exist_ok=True)
    click.echo(f"Created directory '{dir_path}'.")

def rename_path(src, dst, base_dir="."):
    """
    Rename a file or folder using git.
    Assumes the repository is always a Git repository.
    """
    subprocess.run(["git", "mv", src, dst], cwd=base_dir, check=True)
    click.echo(f"Renamed '{src}' to '{dst}' using git mv.")

# =============================
# Doubly Linked List Data Structures
# =============================

class Task:
    def __init__(self, pos, task_name, folder, letter=None):
        self.pos = int(pos)         # numeric part (as integer)
        self.letter = letter        # None if serial; otherwise, a letter (e.g. "a")
        self.task_name = task_name  # task name string
        self.folder = folder        # folder name on disk

    def full_position(self):
        return f"{self.pos}" if self.letter is None else f"{self.pos}{self.letter}"

    def __str__(self):
        return f"[{self.full_position()}] {self.task_name} ({self.folder})"

class TaskGroup:
    def __init__(self, pos):
        self.pos = int(pos)
        self.tasks = []  # list of Task objects (a single task for serial, multiple for parallel)
        self.prev = None
        self.next = None

    def is_parallel(self):
        return len(self.tasks) > 1 or (self.tasks and self.tasks[0].letter is not None)

    def __str__(self):
        if self.is_parallel():
            inner = ", ".join(str(t) for t in self.tasks)
            return f"Group {self.pos}: [Parallel: {inner}]"
        elif self.tasks:
            return f"Group {self.pos}: {self.tasks[0]}"
        else:
            return f"Group {self.pos}: <empty>"

def get_folder_pattern():
    # Matches folder names like "3_taskName" (serial) or "3a_taskName" (parallel)
    # Group 1: digits; Group 2: optional letters; Group 3: task name part
    return re.compile(r"^(\d+)([a-z]*)_(.+)$")

def build_task_groups(base_dir="."):
    """
    Validate the current YAML and folder structure.
    Returns a list of TaskGroup objects (doubly linked) built from Mo.yaml and folder names.
    Raises an Exception if any inconsistency is found.
    """
    yaml_path = os.path.join(base_dir, "Mo.yaml")
    if not os.path.exists(yaml_path):
        raise FileNotFoundError("Mo.yaml not found in current directory!")
    with open(yaml_path, "r") as f:
        mo = yaml.safe_load(f)

    tasks_yaml = mo.get("tasks", {})
    groups = {}
    for key, value in tasks_yaml.items():
        tg = TaskGroup(key)
        if isinstance(value, dict):
            for letter, task_name in value.items():
                folder_name = f"{key}{letter}_{task_name}"
                tg.tasks.append(Task(key, task_name, folder_name, letter))
        else:
            folder_name = f"{key}_{value}"
            tg.tasks.append(Task(key, value, folder_name))
        groups[int(key)] = tg

    folder_pattern = get_folder_pattern()
    found_folders = {}  # maps full position (e.g. "3" or "3a") to folder name
    for d in os.listdir(base_dir):
        full_path = os.path.join(base_dir, d)
        if os.path.isdir(full_path):
            m = folder_pattern.match(d)
            if m:
                num, letter, _ = m.groups()
                found_folders[f"{num}{letter}"] = d

    for group in groups.values():
        for task in group.tasks:
            if task.full_position() not in found_folders:
                raise ValueError(f"Folder for task {task.full_position()} ({task.task_name}) not found!")
            task.folder = found_folders[task.full_position()]

    sorted_positions = sorted(groups.keys())
    task_groups = [groups[pos] for pos in sorted_positions]
    for i, group in enumerate(task_groups):
        if i > 0:
            group.prev = task_groups[i - 1]
        if i < len(task_groups) - 1:
            group.next = task_groups[i + 1]
    return task_groups, mo

# =============================
# Helper Functions for YAML and Folder Shifting
# =============================

def save_yaml(mo, base_dir="."):
    safe_write_file(os.path.join(base_dir, "Mo.yaml"), yaml.dump(mo))

def shift_task_groups(start_pos, mo, base_dir="."):
    """
    Shift every task group (both in YAML and folders) with numeric key >= start_pos upward by 1.
    (Processing in descending order to avoid collisions.)
    """
    tasks_yaml = mo.get("tasks", {})
    # Get all task folders in the directory
    folder_pattern = get_folder_pattern()
    task_folders = {}
    for d in os.listdir(base_dir):
        full_path = os.path.join(base_dir, d)
        if os.path.isdir(full_path):
            m = folder_pattern.match(d)
            if m:
                num, letter, _ = m.groups()
                pos = int(num)
                if pos >= int(start_pos):
                    task_folders[d] = full_path

    # Sort folders in reverse order to avoid collisions
    sorted_folders = sorted(task_folders.keys(), reverse=True)
    
    # First rename all affected folders
    for folder_name in sorted_folders:
        m = folder_pattern.match(folder_name)
        if m:
            num, letter, task_name = m.groups()
            pos = int(num)
            new_pos = str(pos + 1)
            old_path = task_folders[folder_name]
            new_folder = f"{new_pos}{letter}_{task_name}"
            new_path = os.path.join(base_dir, new_folder)
            if os.path.exists(old_path):
                backup = backup_path(old_path)
                click.echo(f"Backed up folder '{old_path}' to '{backup}'.")
                rename_path(old_path, new_path, base_dir)
    # Then update the YAML
    keys_to_shift = sorted([int(k) for k in tasks_yaml.keys() if int(k) >= int(start_pos)], reverse=True)
    for k in keys_to_shift:
        new_key = str(k + 1)
        tasks_yaml[new_key] = tasks_yaml.pop(str(k))
    mo["tasks"] = tasks_yaml

def parse_position(pos_str):
    """
    Parse a position string like "3" or "3a" into (numeric_part, letter_or_None).
    """
    digits = ""
    letters = ""
    for ch in pos_str:
        if ch.isdigit():
            digits += ch
        else:
            letters += ch
    if not digits:
        raise ValueError("Position must start with a number.")
    return digits, letters if letters else None

# =============================
# Core Operations: add, delete, and move
# (The convert operation has been removed.)
# =============================

def add_task(base_dir, pos_str, task_name):
    """
    Add a new task.
      - For sequential tasks (no letter), if the target group exists then shift groups.
      - For parallel tasks (letter provided), if the group at pos is serial then convert it.
    Creates a new folder and writes template files.
    """
    # Try to load existing Mo.yaml, if not found create a new one
    yaml_path = os.path.join(base_dir, "Mo.yaml")
    if os.path.exists(yaml_path):
        with open(yaml_path, "r") as f:
            mo = yaml.safe_load(f)
    else:
        raise FileNotFoundError("Mo.yaml not found. Please initialize the project first.")

    task_groups, _ = build_task_groups(base_dir)
    current_group_count = len(task_groups)
    pos, letter = parse_position(pos_str)
    if int(pos) > current_group_count + 1:
        raise ValueError(f"Position cannot be more than {current_group_count + 1} (got {pos}).")
    tasks_yaml = mo.get("tasks", {})

    if letter is None:
        if pos not in tasks_yaml:
            tasks_yaml[pos] = task_name
        else:
            shift_task_groups(pos, mo, base_dir)
            tasks_yaml[pos] = task_name
            click.echo(f"Shifted groups from position {pos} onward to insert new sequential task.")
    else:
        if pos not in tasks_yaml:
            tasks_yaml[pos] = { letter: task_name }
        else:
            if isinstance(tasks_yaml[pos], dict):
                if letter in tasks_yaml[pos]:
                    raise ValueError(f"Task {pos}{letter} already exists.")
                tasks_yaml[pos][letter] = task_name
            else:
                existing_task = tasks_yaml[pos]
                # Convert existing sequential task to parallel 'b' position
                old_folder = os.path.join(base_dir, f"{pos}_{existing_task}")
                new_folder = os.path.join(base_dir, f"{pos}b_{existing_task}")
                if os.path.exists(old_folder):
                    if click.confirm(f"Convert sequential task at {pos} to parallel (rename folder '{old_folder}' to '{new_folder}')?", default=False):
                        backup = backup_path(old_folder)
                        click.echo(f"Backed up folder '{old_folder}' to '{backup}'.")
                        rename_path(old_folder, new_folder, base_dir)
                        click.echo(f"Converted sequential task at position {pos} to parallel.")
                    else:
                        raise ValueError("Cannot add parallel task without converting existing serial task.")
                # Place existing task at 'b' and new task at requested position
                tasks_yaml[pos] = {"b": existing_task, letter: task_name}

    # First create the task folder and its contents
    folder_prefix = pos if letter is None else f"{pos}{letter}"
    task_folder = os.path.join(base_dir, f"{folder_prefix}_{task_name}")
    safe_create_directory(task_folder)

    task_file_path = os.path.join(task_folder, f"{task_name}.py")
    safe_write_file(task_file_path, get_task_template(task_name))
    reqs_file_path = os.path.join(task_folder, "requirements.txt")
    reqs_content = '-r ../requirements.txt'
    safe_write_file(reqs_file_path, reqs_content)
    
    # Only create wrapper file if wrappers directory exists
    wrappers_folder = os.path.join(base_dir, "wrappers")
    if os.path.exists(wrappers_folder):
        wrapper_file_path = os.path.join(wrappers_folder, f"{task_name}_wrapper.py")
        safe_write_file(wrapper_file_path, get_wrapper_template(task_name))
    
    # Update Mo.yaml with new task order
    mo["tasks"] = tasks_yaml
    with open(yaml_path, "w") as f:
        yaml.dump(mo, f)
    click.echo(f"Added task '{task_name}' at position '{pos_str}'. Created folder '{task_folder}'.")

def delete_task(base_dir, pos_str):
    """
    Delete a task.
    Supply the full position (e.g. "3" for a serial task or "3b" for a parallel task).
    After deletion, later groups are shifted upward.
    """
    task_groups, mo = build_task_groups(base_dir)
    tasks_yaml = mo.get("tasks", {})
    pos, letter = parse_position(pos_str)
    if pos not in tasks_yaml:
        raise ValueError(f"No task group found at position {pos}.")
    # Delete entire group if serial.
    if letter is None and not isinstance(tasks_yaml[pos], dict):
        folder = os.path.join(base_dir, f"{pos}_{tasks_yaml[pos]}")
        if os.path.exists(folder):
            if click.confirm(f"Delete folder '{folder}'?", default=False):
                backup = backup_path(folder)
                click.echo(f"Backed up folder '{folder}' to '{backup}'.")
                shutil.rmtree(folder)
                click.echo(f"Deleted folder '{folder}'.")
        tasks_yaml.pop(pos)
        shift_task_groups(int(pos)+1, mo, base_dir)
        click.echo(f"Deleted group at position {pos} and shifted later groups.")
    else:
        # For parallel tasks:
        if not isinstance(tasks_yaml[pos], dict):
            raise ValueError(f"Group at position {pos} is serial; no parallel task to delete.")
        if letter not in tasks_yaml[pos]:
            raise ValueError(f"No task found at position {pos}{letter}.")
        task_name = tasks_yaml[pos].pop(letter)
        folder = os.path.join(base_dir, f"{pos}{letter}_{task_name}")
        if os.path.exists(folder):
            if click.confirm(f"Delete folder '{folder}'?", default=False):
                backup = backup_path(folder)
                click.echo(f"Backed up folder '{folder}' to '{backup}'.")
                shutil.rmtree(folder)
                click.echo(f"Deleted folder '{folder}'.")
        if len(tasks_yaml[pos]) == 1:
            (remaining_letter, remaining_task) = list(tasks_yaml[pos].items())[0]
            old_folder = os.path.join(base_dir, f"{pos}{remaining_letter}_{remaining_task}")
            new_folder = os.path.join(base_dir, f"{pos}_{remaining_task}")
            if os.path.exists(old_folder):
                if click.confirm(f"Flatten group by renaming '{old_folder}' to '{new_folder}'?", default=False):
                    backup = backup_path(old_folder)
                    click.echo(f"Backed up folder '{old_folder}' to '{backup}'.")
                    rename_path(old_folder, new_folder, base_dir)
                    click.echo(f"Flattened group: renamed '{old_folder}' to '{new_folder}'.")
            tasks_yaml[pos] = remaining_task
        click.echo(f"Deleted parallel task at position {pos}{letter}.")
    mo["tasks"] = tasks_yaml
    save_yaml(mo, base_dir)

def move_task(base_dir, from_pos_str, to_pos_str):
    """
    Move a task from one position to another.
    Both source and destination are supplied as combined strings (e.g. "3a" or "2").
    The task is removed from its original position (shifting groups upward if needed)
    and reinserted at the destination (shifting groups downward if needed).
    Works for both serial and parallel tasks.
    """
    # First, remove the source task from its position.
    task_groups, mo = build_task_groups(base_dir)
    tasks_yaml = mo.get("tasks", {})
    from_num, from_letter = parse_position(from_pos_str)
    if from_num not in tasks_yaml:
        raise ValueError(f"Source position {from_num} not found.")
    if isinstance(tasks_yaml[from_num], dict):
        if not from_letter or from_letter not in tasks_yaml[from_num]:
            raise ValueError(f"Task at {from_pos_str} not found in parallel group.")
        task_name = tasks_yaml[from_num].pop(from_letter)
        source_folder = os.path.join(base_dir, f"{from_num}{from_letter}_{task_name}")
        if len(tasks_yaml[from_num]) == 1:
            (rem_letter, rem_task) = list(tasks_yaml[from_num].items())[0]
            old_folder = os.path.join(base_dir, f"{from_num}{rem_letter}_{rem_task}")
            new_folder = os.path.join(base_dir, f"{from_num}_{rem_task}")
            if os.path.exists(old_folder):
                if click.confirm(f"Flatten group at position {from_num} by renaming '{old_folder}' to '{new_folder}'?", default=False):
                    backup = backup_path(old_folder)
                    click.echo(f"Backed up folder '{old_folder}' to '{backup}'.")
                    rename_path(old_folder, new_folder, base_dir)
                    click.echo(f"Flattened group at position {from_num}.")
            tasks_yaml[from_num] = rem_task
    else:
        if from_letter:
            raise ValueError("No letter expected for a serial task.")
        task_name = tasks_yaml[from_num]
        source_folder = os.path.join(base_dir, f"{from_num}_{task_name}")
        tasks_yaml.pop(from_num)
        shift_task_groups(int(from_num)+1, mo, base_dir)
    # Now, insert the moved task at destination.
    to_num, to_letter = parse_position(to_pos_str)
    new_task_groups, _ = build_task_groups(base_dir)
    current_group_count = len(new_task_groups)
    if int(to_num) > current_group_count + 1:
        raise ValueError(f"Destination position cannot be more than {current_group_count + 1}.")
    if to_letter is None:
        if to_num not in tasks_yaml:
            tasks_yaml[to_num] = task_name
        else:
            shift_task_groups(to_num, mo, base_dir)
            tasks_yaml[to_num] = task_name
        dest_folder_prefix = to_num
    else:
        if to_num not in tasks_yaml:
            tasks_yaml[to_num] = { to_letter: task_name }
        else:
            if isinstance(tasks_yaml[to_num], dict):
                if to_letter in tasks_yaml[to_num]:
                    raise ValueError(f"Destination {to_num}{to_letter} already exists.")
                tasks_yaml[to_num][to_letter] = task_name
            else:
                existing_task = tasks_yaml[to_num]
                old_folder = os.path.join(base_dir, f"{to_num}_{existing_task}")
                new_folder_existing = os.path.join(base_dir, f"{to_num}a_{existing_task}")
                if os.path.exists(old_folder):
                    if click.confirm(f"Convert serial group at {to_num} to parallel by renaming '{old_folder}' to '{new_folder_existing}'?", default=False):
                        backup = backup_path(old_folder)
                        click.echo(f"Backed up folder '{old_folder}' to '{backup}'.")
                        rename_path(old_folder, new_folder_existing, base_dir)
                        click.echo(f"Converted serial group at position {to_num} to parallel.")
                    else:
                        raise ValueError("Cannot move into parallel position without converting existing serial task.")
                tasks_yaml[to_num] = {"a": existing_task, to_letter: task_name}
        dest_folder_prefix = f"{to_num}{to_letter}"
    new_folder = os.path.join(base_dir, f"{dest_folder_prefix}_{task_name}")
    if os.path.exists(source_folder):
        shutil.move(source_folder, new_folder)
        click.echo(f"Moved folder from '{source_folder}' to '{new_folder}'.")
    else:
        click.echo(f"Source folder '{source_folder}' does not exist; nothing moved on disk.")
    click.echo(f"Moved task '{task_name}' from {from_pos_str} to {to_pos_str}.")
    mo["tasks"] = tasks_yaml
    save_yaml(mo, base_dir)

# =============================
# CLI Commands using Click
# (Note: the convert operation has been removed.)
# =============================

@click.group()
def cli():
    """Model Organizer: manage the project folder structure and tasks."""
    pass

@cli.command()
@click.option('--model', prompt="Model name", help="Name of the model.")
def init(model):
    """Initialize a new model project in the current directory."""
    # Create directory with model name, replacing spaces with underscores
    base_dir = model.replace(" ", "_")
    safe_create_directory(base_dir)
    safe_create_directory(os.path.join(base_dir, "wrappers"))
    safe_create_directory(os.path.join(base_dir, "config"))
    safe_create_directory(os.path.join(base_dir, "tests"))
    safe_create_directory(os.path.join(base_dir, "utils"))
    safe_write_file(os.path.join(base_dir, "config", ".env"), "# environment variables go here\n")
    safe_write_file(os.path.join(base_dir, "tox.ini"), get_tox_config_template())
    safe_write_file(os.path.join(base_dir, "requirements.txt"), get_requirements_template())
    # Create build.sh and set executable permissions
    build_sh_path = os.path.join(base_dir, "build.sh")
    safe_write_file(build_sh_path, get_build_sh_template())
    os.chmod(build_sh_path, 0o755)
    mo = {"model": model, "tasks": {}}
    safe_write_file(os.path.join(base_dir, "Mo.yaml"), yaml.dump(mo))
    click.echo(f"Initialized model '{model}' in {os.path.abspath(base_dir)}.")

@cli.command()
@click.option('--pos', required=True, help="Position for the task (e.g., '1' or '3a').")
@click.option('--name', required=True, help="Name of the task.")
def add(pos, name):
    """Add a new task to the project."""
    try:
        add_task(".", pos, name)
    except Exception as e:
        click.echo(f"Error adding task: {e}")

@cli.command()
@click.option('--pos', required=True, help="Full position of the task to delete (e.g., '3' for serial or '3b' for parallel).")
def delete(pos):
    """Delete a task (or a parallel subtask)."""
    try:
        delete_task(".", pos)
    except Exception as e:
        click.echo(f"Error deleting task: {e}")

@cli.command()
@click.option('--from', 'from_pos', required=True, help="Source position of the task to move (e.g., '3a' or '2').")
@click.option('--to', 'to_pos', required=True, help="Destination position (e.g., '4' or '5a').")
def move(from_pos, to_pos):
    """Move a task from one position to another."""
    try:
        move_task(".", from_pos, to_pos)
    except Exception as e:
        click.echo(f"Error moving task: {e}")

@cli.command()
def validate():
    """Validate that Mo.yaml and task folders are consistent."""
    try:
        task_groups, _ = build_task_groups(".")
        click.echo("Validation successful. Current tasks (doubly linked list):")
        for group in task_groups:
            prev_str = f"{group.prev.pos}" if group.prev else "None"
            next_str = f"{group.next.pos}" if group.next else "None"
            click.echo(f"Group {group.pos} (prev: {prev_str}, next: {next_str}):")
            for t in group.tasks:
                click.echo(f"  - {t.full_position()}: {t.task_name}")
    except Exception as e:
        click.echo(f"Validation error: {e}")

if __name__ == '__main__':
    cli()
