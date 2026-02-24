ARG AIRFLOW_IMAGE_TAG=2.10.5-python3.11
FROM apache/airflow:${AIRFLOW_IMAGE_TAG}

USER airflow
COPY requirements-airflow.txt /tmp/requirements-airflow.txt
RUN pip install --no-cache-dir -r /tmp/requirements-airflow.txt

WORKDIR /opt/project
COPY --chown=airflow:0 src /opt/project/src
ENV PYTHONPATH=/opt/project/src
