#!/usr/bin/env python3
"""
Auto-generated test script for task: task1 (position 1)
"""
import subprocess
import sys

def test_task():
    result = subprocess.run(["python3", "../1_task1/task1.py"], capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        sys.exit(result.returncode)

if __name__ == '__main__':
    test_task()
