from datetime import datetime, timedelta
import os, boto3, time
from airflow import DAG
from airflow.operators.python import PythonOperator

AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-2")
DATABASE = "iot_pipeline"
TABLE = "silver_iot_events"
ATHENA_OUTPUT = "s3://athena-query-results-your-suffix/"
SNS_TOPIC_ARN = "arn:aws:sns:us-east-2:YOUR_ACCOUNT_ID:iot-anomaly-alerts"

def athena_query(sql: str) -> dict:
    ath = boto3.client("athena", region_name=AWS_REGION)
    start = ath.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": DATABASE},
        ResultConfiguration={"OutputLocation": ATHENA_OUTPUT},
    )
    qid = start["QueryExecutionId"]
    while True:
        res = ath.get_query_execution(QueryExecutionId=qid)
        state = res["QueryExecution"]["Status"]["State"]
        if state in ("SUCCEEDED","FAILED","CANCELLED"):
            break
        time.sleep(2)
    if state != "SUCCEEDED":
        raise RuntimeError(f"Athena failed: {state}")
    return {"QueryExecutionId": qid}

def task_repair_partitions():
    athena_query(f"MSCK REPAIR TABLE {TABLE}")

def task_anomaly_check(**ctx):
    sql = f"""
    SELECT COUNT(*) AS c
    FROM {TABLE}
    WHERE event_date = current_date
      AND is_anomaly = true
    """
    ath = boto3.client("athena", region_name=AWS_REGION)
    res = athena_query(sql)
    qid = res["QueryExecutionId"]
    # fetch results
    out = ath.get_query_results(QueryExecutionId=qid)
    # first row is header; second row has the count
    rows = out.get("ResultSet", {}).get("Rows", [])
    count = int(rows[1]["Data"][0]["VarCharValue"]) if len(rows) > 1 else 0
    # push to XCom
    ctx["ti"].xcom_push(key="anomaly_count", value=count)

def task_notify(**ctx):
    count = ctx["ti"].xcom_pull(key="anomaly_count", task_ids="anomaly_check")
    if count and int(count) > 0:
        sns = boto3.client("sns", region_name=AWS_REGION)
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject="IoT Anomaly Detected",
            Message=f"Detected {count} anomalies in Silver today."
        )

default_args = {
    "owner": "you",
    "retries": 0,
}

with DAG(
    "iot_monitoring",
    default_args=default_args,
    start_date=datetime(2025, 8, 1),
    schedule_interval="*/15 * * * *",
    catchup=False,
) as dag:

    repair_partitions = PythonOperator(
        task_id="repair_partitions",
        python_callable=task_repair_partitions,
    )

    anomaly_check = PythonOperator(
        task_id="anomaly_check",
        python_callable=task_anomaly_check,
        provide_context=True,
    )

    notify = PythonOperator(
        task_id="notify",
        python_callable=task_notify,
        provide_context=True,
    )

    repair_partitions >> anomaly_check >> notify
