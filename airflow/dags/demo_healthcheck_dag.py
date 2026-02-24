# Docs:
# - artifacts/docs/data/4.2 Оркестрация Airflow end-to-end (MVP).md
# - artifacts/docs/README.md

from datetime import datetime

from airflow import DAG
from airflow.operators.empty import EmptyOperator


with DAG(
    dag_id="demo_healthcheck",
    start_date=datetime(2024, 1, 1),
    schedule="@daily",
    catchup=False,
    tags=["demo"],
) as dag:
    start = EmptyOperator(task_id="start")
    finish = EmptyOperator(task_id="finish")

    start >> finish
