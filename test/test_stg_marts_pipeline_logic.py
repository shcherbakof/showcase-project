import unittest

from src.jobs.stg_marts_pipeline_logic import build_error_summary, compute_pipeline_status, evaluate_quality


class StgMartsPipelineLogicTests(unittest.TestCase):
    def test_evaluate_quality_ok(self) -> None:
        result = evaluate_quality(
            snapshot_rows=10,
            market_rows=20,
            employer_rows=30,
            unknown_bucket_rows=0,
            avg_salary_coverage_pct=55.5,
            unknown_warn_threshold=1,
            salary_coverage_warn_threshold=20.0,
        )

        self.assertEqual(result["quality_label"], "ok")
        self.assertEqual(result["critical_issues"], [])
        self.assertEqual(result["warnings"], [])

    def test_evaluate_quality_failed_on_empty_snapshot(self) -> None:
        result = evaluate_quality(
            snapshot_rows=0,
            market_rows=10,
            employer_rows=10,
            unknown_bucket_rows=0,
            avg_salary_coverage_pct=50.0,
            unknown_warn_threshold=1,
            salary_coverage_warn_threshold=20.0,
        )

        self.assertEqual(result["quality_label"], "failed")
        self.assertIn("error_code=DQ_CRITICAL_SNAPSHOT_EMPTY", result["critical_issues"])

    def test_compute_pipeline_status_partial_on_excel_failure(self) -> None:
        status = compute_pipeline_status(
            failed_tasks=["generate_excel_report"],
            quality_label="ok",
        )

        self.assertEqual(status["status"], "partial")
        self.assertFalse(status["has_critical_error"])
        self.assertTrue(status["excel_failed"])

    def test_compute_pipeline_status_failed_on_critical_task(self) -> None:
        status = compute_pipeline_status(
            failed_tasks=["refresh_marts", "generate_excel_report"],
            quality_label="warning",
        )

        self.assertEqual(status["status"], "failed")
        self.assertTrue(status["has_critical_error"])
        self.assertIn("refresh_marts", status["critical_failed_tasks"])

    def test_build_error_summary(self) -> None:
        summary = build_error_summary(
            critical_failed_tasks=["refresh_marts"],
            excel_failed=True,
            critical_issues=["error_code=DQ_CRITICAL_MARKET_EMPTY"],
            warnings=["warning_code=DQ_LOW_SALARY_COVERAGE avg_salary_coverage_pct=10.00"],
            quality_marker_path="artifacts/reports/excel_quality/run.json",
            excel_output_path="artifacts/reports/excel/report.xlsx",
        )

        self.assertIsNotNone(summary)
        text = summary or ""
        self.assertIn("upstream_failed_tasks=refresh_marts", text)
        self.assertIn("warning_code=EXCEL_BUILD_FAILED", text)
        self.assertIn("quality_marker=", text)


if __name__ == "__main__":
    unittest.main()
