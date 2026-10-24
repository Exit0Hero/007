"""Tests for the minimal CLI entry point (US-502, US-503).

Every test passes an explicit ``environ`` mapping so results are deterministic
regardless of the host machine's environment, and no paid API call is possible.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from atlas.config import ENV_MODE, ENV_MODEL, ENV_OPENAI_KEY, ENV_TAVILY_KEY
from atlas.main import (
    EXIT_CONFIGURATION_ERROR,
    EXIT_INVALID_REQUEST,
    EXIT_OK,
    main,
)
from atlas.models import MAX_QUESTION_LENGTH

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"


def run(argv: list[str], environ: dict[str, str] | None = None) -> tuple[int, str, str]:
    """Invoke main() in-process, capturing its exit code and output."""
    import contextlib
    import io

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv, environ={} if environ is None else environ)
    return code, out.getvalue(), err.getvalue()


def test_valid_question_in_offline_mode_succeeds() -> None:
    code, out, err = run(["What is a research agent?"])

    assert code == EXIT_OK
    assert err == ""
    assert "mode: offline" in out
    assert "requires ATLAS_MODE=live" in out


def test_accepted_output_does_not_reveal_secrets() -> None:
    secret = "sk-must-never-be-printed"
    code, out, err = run(
        ["What is Atlas?"],
        {ENV_MODE: "offline", ENV_OPENAI_KEY: secret},
    )

    assert code == EXIT_OK
    assert secret not in out
    assert secret not in err


@pytest.mark.parametrize("raw", ["", "   ", "\t"])
def test_invalid_request_returns_exit_code_3(raw: str) -> None:
    code, out, err = run([raw])

    assert code == EXIT_INVALID_REQUEST
    assert out == ""
    assert "error:" in err


def test_over_length_request_returns_exit_code_3() -> None:
    code, _, err = run(["a" * (MAX_QUESTION_LENGTH + 1)])

    assert code == EXIT_INVALID_REQUEST
    assert "error:" in err


def test_validation_precedes_configuration_loading() -> None:
    """FR-01: an invalid question must win over a broken live configuration.

    If configuration were read first, this would return EXIT_CONFIGURATION_ERROR.
    """
    broken_live = {
        ENV_MODE: "live",
        ENV_OPENAI_KEY: "",
        ENV_TAVILY_KEY: "",
        ENV_MODEL: "",
    }

    code, _, _ = run(["   "], broken_live)

    assert code == EXIT_INVALID_REQUEST


def test_live_mode_without_credentials_returns_exit_code_4() -> None:
    code, out, err = run(["What is Atlas?"], {ENV_MODE: "live"})

    assert code == EXIT_CONFIGURATION_ERROR
    assert out == ""
    assert ENV_OPENAI_KEY in err


def test_invalid_mode_returns_exit_code_4() -> None:
    code, _, err = run(["What is Atlas?"], {ENV_MODE: "sometimes"})

    assert code == EXIT_CONFIGURATION_ERROR
    assert ENV_MODE in err


def test_non_numeric_limit_returns_exit_code_4() -> None:
    code, _, err = run(["What is Atlas?"], {"ATLAS_MAX_ITERATIONS": "lots"})

    assert code == EXIT_CONFIGURATION_ERROR
    assert "ATLAS_MAX_ITERATIONS" in err


def test_error_output_contains_no_secret_values() -> None:
    secret = "sk-live-secret-value"
    code, out, err = run(
        ["What is Atlas?"],
        {ENV_MODE: "live", ENV_OPENAI_KEY: secret},
    )

    assert code == EXIT_CONFIGURATION_ERROR
    assert secret not in out
    assert secret not in err


def test_version_flag_exits_zero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"], environ={})

    assert excinfo.value.code == 0


def test_missing_argument_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([], environ={})

    assert excinfo.value.code == 2


def test_module_entry_point_runs_end_to_end() -> None:
    """Prove `python -m atlas.main` actually works, not only main() in-process."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("ATLAS_") and key not in (ENV_OPENAI_KEY, ENV_TAVILY_KEY)
    }
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(SRC_DIR), env.get("PYTHONPATH", "")]))

    result = subprocess.run(
        [sys.executable, "-m", "atlas.main", "What is a bounded agent loop?"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        env=env,
        timeout=60,
        check=False,
    )

    assert result.returncode == EXIT_OK, result.stderr
    assert "status: validated" in result.stdout
