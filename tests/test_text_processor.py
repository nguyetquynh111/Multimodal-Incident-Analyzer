"""Text draft-contract tests"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

import pandas as pd
import pytest

from text.processor import (
    ARTIFACT_COLUMNS,
    _resolve_cli_input,
    analyze_text,
    build_parser,
    process_text,
)


SAMPLE_POST = (
    "Robbery reported on Oak Street near Chicago downtown around 9pm tonight. "
    "Two suspects fled on foot toward the train station. Police on the scene. "
    "No injuries reported. Witnesses say one suspect was carrying a knife."
)


def test_analyze_text_returns_exact_contract_and_supported_labels() -> None:
    row = analyze_text("TXT_112", SAMPLE_POST, source="Twitter")

    assert list(row) == ARTIFACT_COLUMNS
    assert row["Text_ID"] == "TXT_112"
    assert row["Source"] == "Twitter"
    assert row["Raw_Text"] == SAMPLE_POST
    assert row["Sentiment"] == "Negative"
    assert row["Topic"] == "Theft / Robbery"
    assert "LOCATION:" in row["Entities"]
    assert "Oak Street" in row["Entities"]
    assert "DATE:" in row["Entities"]


def test_process_text_writes_exact_csv_columns_without_nulls() -> None:
    with tempfile.TemporaryDirectory() as directory:
        input_path = Path(directory) / "social_post.txt"
        output_path = Path(directory) / "text_output.csv"
        input_path.write_text(SAMPLE_POST, encoding="utf-8")

        frame = process_text(input_path, output_csv_path=output_path, source="Twitter")
        saved = pd.read_csv(output_path, keep_default_na=False)

    assert list(frame.columns) == ARTIFACT_COLUMNS
    assert list(saved.columns) == ARTIFACT_COLUMNS
    assert len(saved) == 1
    assert not saved.isnull().values.any()
    assert saved.iloc[0]["Topic"] == "Theft / Robbery"


def test_process_text_dataset_csv_creates_one_row_per_record() -> None:
    with tempfile.TemporaryDirectory() as directory:
        input_path = Path(directory) / "crimereport.csv"
        input_frame = pd.DataFrame(
            [
                {
                    "details": "Fire reported at Central Station today.",
                    "source": "CrimeReport",
                },
                {
                    "details": "Noise complaint near Lake Park last night.",
                    "source": "CrimeReport",
                },
            ]
        )
        input_frame.to_csv(input_path, index=False)

        frame = process_text(input_path, output_csv_path=None)

    assert list(frame.columns) == ARTIFACT_COLUMNS
    assert frame["Text_ID"].tolist() == ["TXT_001", "TXT_002"]
    assert frame["Topic"].tolist() == ["Fire / Arson", "Public Disturbance"]


def test_process_text_folder_combines_supported_files_in_sorted_order() -> None:
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        (folder / "a_post.txt").write_text(
            "Robbery reported near Union Station tonight.",
            encoding="utf-8",
        )
        pd.DataFrame(
            [
                {
                    "details": "Fire reported at Central Station today.",
                    "source": "CrimeReport",
                },
                {
                    "details": "Crash blocking Lake Shore Drive this morning.",
                    "source": "CrimeReport",
                },
            ]
        ).to_csv(folder / "b_reports.csv", index=False)

        frame = process_text(folder, output_csv_path=None)

    assert list(frame.columns) == ARTIFACT_COLUMNS
    assert frame["Text_ID"].tolist() == ["TXT_001", "TXT_002", "TXT_003"]
    assert frame["Topic"].tolist() == [
        "Theft / Robbery",
        "Fire / Arson",
        "Traffic Accident",
    ]


def test_process_text_accepts_checked_in_samples_folder() -> None:
    samples = Path(__file__).resolve().parents[1] / "text" / "sample_data"

    frame = process_text(samples, output_csv_path=None)

    assert list(frame.columns) == ARTIFACT_COLUMNS
    assert len(frame) >= 1
    assert frame["Text_ID"].tolist() == [
        f"TXT_{index:03d}" for index in range(1, len(frame) + 1)
    ]


def test_process_text_json_lines_txt_creates_one_row_per_record() -> None:
    records = [
        {
            "text": "Police investigating shooting in Pontchartrain Park",
            "created_at": "Sat Feb 01 06:06:04 +0000 2014",
            "place": {"full_name": "New Orleans, LA"},
            "user": {"name": "NOLA.com", "location": "New Orleans, LA"},
        },
        {
            "text": "Town of Tonawanda Police Search for Bank Robbery Suspect",
            "created_at": "Thu Jan 30 22:19:37 +0000 2014",
            "user": {"name": "WGRZ", "location": "Buffalo, NY"},
        },
    ]

    with tempfile.TemporaryDirectory() as directory:
        input_path = Path(directory) / "CrimeReport.txt"
        input_path.write_text(
            "\n".join(json.dumps(record) for record in records),
            encoding="utf-8",
        )

        frame = process_text(input_path, output_csv_path=None)

    assert list(frame.columns) == ARTIFACT_COLUMNS
    assert frame["Text_ID"].tolist() == ["TXT_001", "TXT_002"]
    assert frame["Source"].tolist() == ["CrimeReport", "CrimeReport"]
    assert frame["Topic"].tolist() == ["Assault / Violence", "Theft / Robbery"]
    assert "DATE:" in frame.iloc[0]["Entities"]
    assert "New Orleans" in frame.iloc[0]["Entities"]


def test_process_text_rejects_json_file() -> None:
    with tempfile.TemporaryDirectory() as directory:
        input_path = Path(directory) / "incidents.json"
        input_path.write_text(
            json.dumps(
                {
                    "incidents": [
                        {
                            "event": "fire",
                            "summary": "Fire reported near Main Street.",
                            "created_at": "2026-06-25",
                        },
                        {
                            "event": "robbery",
                            "description": "Robbery reported downtown.",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="Unsupported text input type"):
            process_text(input_path, output_csv_path=None, source="JSON")


def test_text_cli_accepts_input_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["--input", "text/sample_data/social_post.txt"])

    assert _resolve_cli_input(args, parser) == "text/sample_data/social_post.txt"


def test_text_cli_still_accepts_positional_input() -> None:
    parser = build_parser()
    args = parser.parse_args(["text/sample_data/social_post.txt"])

    assert _resolve_cli_input(args, parser) == "text/sample_data/social_post.txt"


def test_text_cli_rejects_duplicate_input_styles() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["text/sample_data/social_post.txt", "--input", "other.txt"]
    )

    with pytest.raises(SystemExit):
        _resolve_cli_input(args, parser)
