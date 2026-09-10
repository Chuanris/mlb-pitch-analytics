ARG AIRFLOW_VERSION=3.3.1
FROM apache/airflow:${AIRFLOW_VERSION}-python3.12

ARG AIRFLOW_VERSION
COPY requirements.txt requirements-dbt.txt /tmp/mlb-requirements/
RUN pip install --no-cache-dir \
    "apache-airflow==${AIRFLOW_VERSION}" \
    -r /tmp/mlb-requirements/requirements.txt \
    -r /tmp/mlb-requirements/requirements-dbt.txt
