import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd

from src.jobs import business_health_excel_report as report_module


class _FakeCursor:
    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    def execute(self, query: str) -> None:
        self._last_query = query

    def fetchone(self) -> tuple[int]:
        return (1,)


class _FakeConnection:
    def cursor(self) -> _FakeCursor:
        return _FakeCursor()

    def close(self) -> None:
        return None


class BusinessHealthExcelReportTests(unittest.TestCase):
    def _config_path(self, root: Path) -> Path:
        cfg = {
            "contact": {"team": "Data Team", "email": "data@example.com", "note": "MVP"},
            "report": {
                "title": "Business Health",
                "timezone": "Europe/Moscow",
                "sheet_names": {
                    "legend": "Легенда",
                    "summary": "Сводка",
                    "top_regions": "Топ регионы",
                    "top_professions": "Топ профессии",
                    "top_employers": "Топ работодатели",
                    "exceptions": "Исключения",
                },
            },
        }
        path = root / "report.json"
        path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        return path

    def test_build_report_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = self._config_path(root)
            output_dir = root / "out"

            summary_df = pd.DataFrame([{"Дата": pd.Timestamp("2026-02-22"), "Активные вакансии": 100}])
            generic_df = pd.DataFrame([{"Дата": pd.Timestamp("2026-02-22"), "Значение": 1}])

            with patch.object(report_module.psycopg2, "connect", return_value=_FakeConnection()):
                with patch.object(report_module, "_summary_df", return_value=summary_df):
                    with patch.object(report_module, "_top_regions_df", return_value=generic_df):
                        with patch.object(report_module, "_top_professions_df", return_value=generic_df):
                            with patch.object(report_module, "_top_employers_df", return_value=generic_df):
                                with patch.object(report_module, "_exceptions_df", return_value=generic_df):
                                    result = report_module.build_business_health_excel_report(
                                        project_db_uri="postgresql://u:p@localhost:5432/project_db",
                                        output_dir=str(output_dir),
                                        config_path=str(config_path),
                                    )

            self.assertEqual(result["status"], "ok")
            self.assertTrue(Path(result["output_path"]).exists())

    def test_build_report_no_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = self._config_path(root)
            output_dir = root / "out"

            summary_df = pd.DataFrame([{"Дата": None}])
            generic_df = pd.DataFrame([{"Дата": pd.Timestamp("2026-02-22"), "Значение": 1}])

            with patch.object(report_module.psycopg2, "connect", return_value=_FakeConnection()):
                with patch.object(report_module, "_summary_df", return_value=summary_df):
                    with patch.object(report_module, "_top_regions_df", return_value=generic_df):
                        with patch.object(report_module, "_top_professions_df", return_value=generic_df):
                            with patch.object(report_module, "_top_employers_df", return_value=generic_df):
                                with patch.object(report_module, "_exceptions_df", return_value=generic_df):
                                    result = report_module.build_business_health_excel_report(
                                        project_db_uri="postgresql://u:p@localhost:5432/project_db",
                                        output_dir=str(output_dir),
                                        config_path=str(config_path),
                                    )

            self.assertEqual(result["status"], "no_data")
            self.assertTrue(Path(result["output_path"]).exists())

    def test_validate_path_traversal(self) -> None:
        with self.assertRaises(ValueError):
            report_module._validate_safe_local_path("../secret.json", "config_path")

    def test_dry_run_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._config_path(Path(tmp))
            with patch.object(report_module.psycopg2, "connect", return_value=_FakeConnection()):
                result = report_module._dry_run_validation(
                    "postgresql://u:p@localhost:5432/project_db",
                    str(config_path),
                )

            self.assertEqual(result["status"], "dry_run_ok")


if __name__ == "__main__":
    unittest.main()
