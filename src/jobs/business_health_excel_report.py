# Docs:
# - artifacts/docs/data/6.2 Генерация Excel витрины Business Health (MVP).md
# - artifacts/docs/data/6.3 Руководство по Excel витрине Business Health (MVP).md
# - artifacts/docs/artifacts_works_gpt/25_session_summary_2026-02-23_18-47_block_6_excel_mvp_and_notebook.md

from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import pandas as pd
import psycopg2
from openpyxl.styles import Alignment
from zoneinfo import ZoneInfo


MSK_TZ = ZoneInfo("Europe/Moscow")
DEFAULT_OUTPUT_DIR = "artifacts/reports/excel"
DEFAULT_CONFIG_PATH = "src/jobs/config/business_health_report.json"
LOGGER = logging.getLogger("business_health_excel_report")


@dataclass
class ReportContext:
    """Context used to compose report metadata and legend sheet."""

    report_generated_at: datetime
    output_path: Path
    status: str
    reason: str
    data_dt: Optional[str]


def _to_db_params(project_db_uri: str) -> Dict[str, Any]:
    """Convert SQLAlchemy-like URI into psycopg2 connection parameters."""

    parsed = urlparse(project_db_uri)
    return {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "user": parsed.username,
        "password": parsed.password,
        "dbname": (parsed.path or "").lstrip("/"),
        "connect_timeout": int(os.getenv("PROJECT_DB_CONNECT_TIMEOUT_SEC", "10")),
    }


def _load_json(path: Path) -> Dict[str, Any]:
    """Load UTF-8 encoded JSON file from disk."""

    return json.loads(path.read_text(encoding="utf-8"))


def _query_df(conn: Any, sql: str, params: Optional[tuple[Any, ...]] = None) -> pd.DataFrame:
    """Execute SQL query and return dataframe result."""

    return pd.read_sql_query(sql, conn, params=params)


def _build_legend_df(cfg: Dict[str, Any], ctx: ReportContext) -> pd.DataFrame:
    """Build legend tab containing report metadata and operational notes."""

    contact = cfg["contact"]
    report_cfg = cfg["report"]
    return pd.DataFrame(
        [
            {"Параметр": "Название отчета", "Значение": report_cfg.get("title", "Business Health")},
            {"Параметр": "Дата/время формирования", "Значение": ctx.report_generated_at.strftime("%Y-%m-%d %H:%M:%S %Z")},
            {"Параметр": "Таймзона", "Значение": report_cfg.get("timezone", "Europe/Moscow")},
            {"Параметр": "Статус отчета", "Значение": ctx.status},
            {"Параметр": "Причина статуса", "Значение": ctx.reason},
            {"Параметр": "Дата данных", "Значение": ctx.data_dt or "n/a"},
            {"Параметр": "Лист Сводка", "Значение": "Ключевые KPI за актуальную дату данных"},
            {"Параметр": "Лист Топ регионы", "Значение": "Top-10 регионов по активным вакансиям"},
            {"Параметр": "Лист Топ профессии", "Значение": "Top-10 профессий по активным вакансиям"},
            {"Параметр": "Лист Топ работодатели", "Значение": "Top-10 работодателей по активным вакансиям"},
            {"Параметр": "Лист Исключения", "Значение": "Сигналы рисков и причины no_data"},
            {"Параметр": "Контактная команда", "Значение": contact.get("team", "")},
            {"Параметр": "Email", "Значение": contact.get("email", "")},
            {"Параметр": "Примечание", "Значение": contact.get("note", "")},
        ]
    )


def _summary_df(conn: Any) -> pd.DataFrame:
    """Load summary KPI sheet dataset."""

    sql = """
    select
      dt as "Дата",
      active_vacancies_today as "Активные вакансии",
      new_vacancies_today as "Новые вакансии",
      closed_vacancies_today as "Закрытые вакансии",
      net_change_today as "Чистое изменение",
      salary_coverage_pct_today as "Доля вакансий с зарплатой (%)",
      median_salary_mid_today as "Медианная зарплата",
      p25_salary_mid_today as "Зарплата p25",
      p75_salary_mid_today as "Зарплата p75",
      active_change_pct_dod as "Изменение активных DoD (%)",
      active_drop_severity as "Сигнал падения активности",
      checked_at as "Время расчета"
    from mon.v_business_health_kpi_cards
    """
    return _query_df(conn, sql)


def _top_regions_df(conn: Any) -> pd.DataFrame:
    """Load top regions sheet dataset."""

    sql = """
    with latest_dt as (
      select max(dt) as dt from mart.market_daily_kpis
    ), ranked as (
      select
        m.dt,
        m.region_norm,
        sum(m.active_vacancies)::int as active_vacancies,
        row_number() over (order by sum(m.active_vacancies) desc, m.region_norm asc) as rank_no
      from mart.market_daily_kpis m
      join latest_dt l on l.dt = m.dt
      group by m.dt, m.region_norm
    )
    select
      dt as "Дата",
      rank_no as "Место",
      region_norm as "Регион",
      active_vacancies as "Активные вакансии"
    from ranked
    where rank_no <= 10
    order by rank_no
    """
    return _query_df(conn, sql)


def _top_professions_df(conn: Any) -> pd.DataFrame:
    """Load top professions sheet dataset."""

    sql = """
    with latest_dt as (
      select max(dt) as dt from mart.market_daily_kpis
    ), ranked as (
      select
        m.dt,
        m.profession_norm,
        sum(m.active_vacancies)::int as active_vacancies,
        row_number() over (order by sum(m.active_vacancies) desc, m.profession_norm asc) as rank_no
      from mart.market_daily_kpis m
      join latest_dt l on l.dt = m.dt
      group by m.dt, m.profession_norm
    )
    select
      dt as "Дата",
      rank_no as "Место",
      profession_norm as "Профессия",
      active_vacancies as "Активные вакансии"
    from ranked
    where rank_no <= 10
    order by rank_no
    """
    return _query_df(conn, sql)


def _top_employers_df(conn: Any) -> pd.DataFrame:
    """Load top employers sheet dataset."""

    sql = """
    with latest_dt as (
      select max(dt) as dt from mart.employer_activity
    ), ranked as (
      select
        e.dt,
        e.employer_key,
        e.region_norm,
        sum(e.active_vacancies)::int as active_vacancies,
        row_number() over (
          order by sum(e.active_vacancies) desc, e.employer_key asc, e.region_norm asc
        ) as rank_no
      from mart.employer_activity e
      join latest_dt l on l.dt = e.dt
      group by e.dt, e.employer_key, e.region_norm
    )
    select
      dt as "Дата",
      rank_no as "Место",
      employer_key as "Работодатель",
      region_norm as "Регион",
      active_vacancies as "Активные вакансии"
    from ranked
    where rank_no <= 10
    order by rank_no
    """
    return _query_df(conn, sql)


def _exceptions_df(conn: Any, status: str, reason: str) -> pd.DataFrame:
    """Load exceptions sheet dataset and prepend report status marker."""

    sql = """
    with latest as (
      select
        dt,
        active_change_pct,
        active_drop_severity,
        active_cnt,
        lag(active_cnt) over (order by dt) as active_cnt_prev
      from mon.v_business_health_dynamics_daily
      order by dt desc
      limit 7
    )
    select
      dt as "Дата",
      active_cnt as "Активные вакансии",
      active_cnt_prev as "Активные вакансии (предыдущий день)",
      active_change_pct as "Изменение активных DoD (%)",
      active_drop_severity as "Сигнал",
      case
        when active_drop_severity = 'error' then 'Критическое падение активных вакансий'
        when active_drop_severity = 'warning' then 'Предупреждение: заметное падение активных вакансий'
        else 'OK'
      end as "Комментарий"
    from latest
    order by dt desc
    """
    df = _query_df(conn, sql)

    summary_row = pd.DataFrame(
        [
            {
                "Дата": None,
                "Активные вакансии": None,
                "Активные вакансии (предыдущий день)": None,
                "Изменение активных DoD (%)": None,
                "Сигнал": status,
                "Комментарий": reason,
            }
        ]
    )
    return pd.concat([summary_row, df], ignore_index=True)


def _to_multiline_header(name: str) -> str:
    """Split header title into two lines for compact Excel layout."""

    words = name.split()
    if len(words) < 2:
        return name
    split_at = max(1, len(words) // 2)
    return " ".join(words[:split_at]) + "\n" + " ".join(words[split_at:])


def _write_excel(
    output_path: Path,
    sheet_names: Dict[str, str],
    legend_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    top_regions_df: pd.DataFrame,
    top_professions_df: pd.DataFrame,
    top_employers_df: pd.DataFrame,
    exceptions_df: pd.DataFrame,
) -> None:
    """Render all report sheets to XLSX file with common formatting."""

    def _sanitize_excel_df(df: pd.DataFrame) -> pd.DataFrame:
        clean = df.copy()
        for col in clean.columns:
            if isinstance(clean[col].dtype, pd.DatetimeTZDtype):
                clean[col] = clean[col].dt.tz_localize(None)
        return clean

    legend_df = _sanitize_excel_df(legend_df)
    summary_df = _sanitize_excel_df(summary_df)
    top_regions_df = _sanitize_excel_df(top_regions_df)
    top_professions_df = _sanitize_excel_df(top_professions_df)
    top_employers_df = _sanitize_excel_df(top_employers_df)
    exceptions_df = _sanitize_excel_df(exceptions_df)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        legend_df.to_excel(writer, index=False, sheet_name=sheet_names["legend"])
        summary_df.to_excel(writer, index=False, sheet_name=sheet_names["summary"])
        top_regions_df.to_excel(writer, index=False, sheet_name=sheet_names["top_regions"])
        top_professions_df.to_excel(writer, index=False, sheet_name=sheet_names["top_professions"])
        top_employers_df.to_excel(writer, index=False, sheet_name=sheet_names["top_employers"])
        exceptions_df.to_excel(writer, index=False, sheet_name=sheet_names["exceptions"])

        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"

            # Header formatting: two-line labels + wrap for compact view.
            for cell in ws[1]:
                if isinstance(cell.value, str):
                    cell.value = _to_multiline_header(cell.value)
                cell.alignment = Alignment(wrap_text=True, vertical="center")
            ws.row_dimensions[1].height = 32

            # Column width is derived from header text length (not data body).
            for col in ws.columns:
                header_val = str(col[0].value or "")
                header_lines = header_val.split("\n")
                header_len = max((len(line) for line in header_lines), default=0)
                ws.column_dimensions[col[0].column_letter].width = min(max(header_len + 2, 10), 36)


def build_business_health_excel_report(
    project_db_uri: str,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    config_path: str = DEFAULT_CONFIG_PATH,
) -> Dict[str, Any]:
    """Build Business Health Excel report and return generation metadata."""

    cfg = _load_json(Path(config_path))
    sheet_names = cfg.get("report", {}).get("sheet_names", {})

    report_generated_at = datetime.now(MSK_TZ)
    file_ts = report_generated_at.strftime("%Y-%m-%d_%H-%M-%S")
    output_path = Path(output_dir) / f"business_health_{file_ts}.xlsx"

    conn = psycopg2.connect(**_to_db_params(project_db_uri))
    try:
        summary_df = _summary_df(conn)
        top_regions_df = _top_regions_df(conn)
        top_professions_df = _top_professions_df(conn)
        top_employers_df = _top_employers_df(conn)

        has_data = not summary_df.empty and pd.notna(summary_df.iloc[0].get("Дата"))
        if has_data:
            status = "ok"
            reason = "Отчет сформирован на основе актуальных данных."
            data_dt = str(summary_df.iloc[0]["Дата"])
        else:
            status = "no_data"
            reason = "status=no_data: отсутствуют данные в источниках для формирования витрины."
            data_dt = None
            summary_df = pd.DataFrame(
                [
                    {
                        "Статус": "no_data",
                        "Причина": "Отсутствуют данные в mon.v_business_health_kpi_cards",
                        "Рекомендация": "Проверьте refresh MARTS и источники данных.",
                    }
                ]
            )

        exceptions_df = _exceptions_df(conn, status=status, reason=reason)
    finally:
        conn.close()

    ctx = ReportContext(
        report_generated_at=report_generated_at,
        output_path=output_path,
        status=status,
        reason=reason,
        data_dt=data_dt,
    )

    legend_df = _build_legend_df(cfg, ctx)
    _write_excel(
        output_path=output_path,
        sheet_names=sheet_names,
        legend_df=legend_df,
        summary_df=summary_df,
        top_regions_df=top_regions_df,
        top_professions_df=top_professions_df,
        top_employers_df=top_employers_df,
        exceptions_df=exceptions_df,
    )

    return {
        "status": status,
        "reason": reason,
        "data_dt": data_dt,
        "output_path": str(output_path),
        "generated_at": report_generated_at.isoformat(),
    }


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for report generation command."""

    parser = argparse.ArgumentParser(description="Build Business Health Excel report")
    parser.add_argument("--project-db-uri", default=os.getenv("PROJECT_DB_URI"), help="Project DB URI")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Output directory for xlsx")
    parser.add_argument("--config-path", default=DEFAULT_CONFIG_PATH, help="Report config JSON path")
    parser.add_argument("--dry-run", action="store_true", help="Validate config and DB access without writing file")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()


def _validate_safe_local_path(path_value: str, argument_name: str) -> Path:
    """Validate that user-provided path is local and does not traverse parents."""

    path = Path(path_value)
    if path.is_absolute():
        return path
    if ".." in path.parts:
        raise ValueError(f"error_code=INVALID_PATH_TRAVERSAL argument={argument_name}")
    return path


def _dry_run_validation(project_db_uri: str, config_path: str) -> Dict[str, Any]:
    """Validate JSON config and DB connectivity without producing artifacts."""

    cfg_path = _validate_safe_local_path(config_path, "config_path")
    _load_json(cfg_path)
    conn = psycopg2.connect(**_to_db_params(project_db_uri))
    try:
        with conn.cursor() as cursor:
            cursor.execute("select 1")
            _ = cursor.fetchone()
    finally:
        conn.close()
    return {
        "status": "dry_run_ok",
        "reason": "config and db connection are valid",
        "config_path": str(cfg_path),
    }


def main() -> int:
    """CLI entry point for Business Health Excel report generation."""

    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if not args.project_db_uri:
        raise ValueError("PROJECT_DB_URI is required")

    output_dir = _validate_safe_local_path(args.output_dir, "output_dir")
    config_path = _validate_safe_local_path(args.config_path, "config_path")

    if args.dry_run:
        result = _dry_run_validation(args.project_db_uri, str(config_path))
        LOGGER.info(
            "dry_run completed status=%s reason=%s config_path=%s",
            result["status"],
            result["reason"],
            result["config_path"],
        )
        return 0

    result = build_business_health_excel_report(
        project_db_uri=args.project_db_uri,
        output_dir=str(output_dir),
        config_path=str(config_path),
    )
    LOGGER.info(
        "report generated status=%s data_dt=%s output_path=%s generated_at=%s",
        result["status"],
        result["data_dt"],
        result["output_path"],
        result["generated_at"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
