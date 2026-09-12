import pathlib
import re
import subprocess

SCRIPT_PATH = pathlib.Path(__file__).parent.parent / "build_image.sh"


def test_get_timestamp_with_epochrealtime():
    cmd = ["bash", "-c", f'source {SCRIPT_PATH} && ts="" && get_timestamp ts && echo "$ts"']
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    ts = result.stdout.strip()
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}$", ts)


def test_get_timestamp_without_epochrealtime():
    cmd = ["bash", "-c", f'unset EPOCHREALTIME && source {SCRIPT_PATH} && ts="" && get_timestamp ts && echo "$ts"']
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    ts = result.stdout.strip()
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", ts)


def test_print_log_with_timestamps():
    cmd = ["bash", "-c", f'source {SCRIPT_PATH} && echo "test log line" | print_log_with_timestamps']
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    output = result.stdout.strip()
    assert re.match(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\] test log line$", output)
