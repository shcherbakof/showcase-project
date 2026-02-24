# Docs:
# - artifacts/docs/data/3.2.3 STG загрузка vacancies из RAW (MVP).md
# - artifacts/docs/data/3.3.2 Витрины MARTS (MVP).md
# - artifacts/docs/data/3.3.3 Правила консистентности MARTS (MVP).md

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


def evaluate_quality(
    *,
    snapshot_rows: int,
    market_rows: int,
    employer_rows: int,
    unknown_bucket_rows: int,
    avg_salary_coverage_pct: float,
    unknown_warn_threshold: int,
    salary_coverage_warn_threshold: float,
) -> Dict[str, Any]:
    """Compute DQ quality label and issue lists for STG/MARTS pipeline run."""

    critical_issues: List[str] = []
    warnings: List[str] = []

    if snapshot_rows <= 0:
        critical_issues.append("error_code=DQ_CRITICAL_SNAPSHOT_EMPTY")
    if market_rows <= 0:
        critical_issues.append("error_code=DQ_CRITICAL_MARKET_EMPTY")
    if employer_rows <= 0:
        critical_issues.append("error_code=DQ_CRITICAL_EMPLOYER_EMPTY")

    if unknown_bucket_rows >= unknown_warn_threshold:
        warnings.append(f"warning_code=DQ_UNKNOWN_BUCKET_PRESENT rows={unknown_bucket_rows}")
    if avg_salary_coverage_pct < salary_coverage_warn_threshold:
        warnings.append(
            "warning_code=DQ_LOW_SALARY_COVERAGE "
            f"avg_salary_coverage_pct={avg_salary_coverage_pct:.2f}"
        )

    if critical_issues:
        quality_label = "failed"
    elif warnings:
        quality_label = "warning"
    else:
        quality_label = "ok"

    return {
        "quality_label": quality_label,
        "critical_issues": critical_issues,
        "warnings": warnings,
        "unknown_bucket_rows": int(unknown_bucket_rows),
        "avg_salary_coverage_pct": round(float(avg_salary_coverage_pct), 2),
    }


def compute_pipeline_status(*, failed_tasks: Sequence[str], quality_label: str) -> Dict[str, Any]:
    """Resolve final pipeline status from failed task list and quality label."""

    critical_failed_tasks = [task for task in failed_tasks if task != "generate_excel_report"]
    has_critical_error = bool(critical_failed_tasks)
    excel_failed = "generate_excel_report" in failed_tasks

    if has_critical_error:
        status = "failed"
    elif excel_failed:
        status = "partial"
    elif quality_label == "warning":
        status = "partial"
    else:
        status = "success"

    return {
        "status": status,
        "has_critical_error": has_critical_error,
        "excel_failed": excel_failed,
        "critical_failed_tasks": critical_failed_tasks,
    }


def build_error_summary(
    *,
    critical_failed_tasks: Sequence[str],
    excel_failed: bool,
    critical_issues: Sequence[str],
    warnings: Sequence[str],
    quality_marker_path: Optional[str],
    excel_output_path: Optional[str],
) -> Optional[str]:
    """Compose error summary string for mon.pipeline_runs."""

    parts: List[str] = []
    if critical_failed_tasks:
        parts.append("upstream_failed_tasks=" + ",".join(critical_failed_tasks))
    if excel_failed:
        parts.append("warning_code=EXCEL_BUILD_FAILED")
    parts.extend(critical_issues)
    parts.extend(warnings)
    if quality_marker_path:
        parts.append(f"quality_marker={quality_marker_path}")
    if excel_output_path:
        parts.append(f"excel_report={excel_output_path}")

    if not parts:
        return None
    return "; ".join(parts)
