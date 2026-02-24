ARG SUPERSET_IMAGE_TAG=4.1.1
FROM apache/superset:${SUPERSET_IMAGE_TAG}

USER root
RUN pip install --no-cache-dir psycopg2-binary==2.9.9

USER superset
