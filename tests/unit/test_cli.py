from typer.testing import CliRunner

from parakh import __version__
from parakh.cli import app


def test_version_prints_package_version():
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"parakh {__version__}"
    assert __version__ == "0.0.1"


def test_budget_notes_rpm_not_estimated():
    from pathlib import Path

    example = Path(__file__).parents[2] / "scenarios" / "hinglish" / "clinic-book-hinglish-01.yaml"
    result = CliRunner().invoke(app, ["budget", str(example)])
    assert result.exit_code == 0
    assert "RPM is not estimated" in result.output
