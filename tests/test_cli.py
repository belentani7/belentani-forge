"""Tests for the CLI entry point."""
import subprocess
import sys


def test_version_flag():
    r = subprocess.run(
        [sys.executable, "-m", "forge", "--version"],
        capture_output=True, text=True, timeout=30,
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]),
    )
    assert r.returncode == 0
    assert "11.0.0" in r.stdout


def test_doctor_runs():
    r = subprocess.run(
        [sys.executable, "-m", "forge", "doctor"],
        capture_output=True, text=True, timeout=60,
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]),
    )
    assert r.returncode == 0
    assert "python" in r.stdout.lower()


def test_help_flag():
    r = subprocess.run(
        [sys.executable, "-m", "forge", "--help"],
        capture_output=True, text=True, timeout=30,
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]),
    )
    assert r.returncode == 0
    assert "BELENTANI FORGE" in r.stdout
