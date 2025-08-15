# Real-Time Anomaly Detection Pipeline


This project implements a **real-time anomaly detection pipeline** using a suite of distributed systems. The architecture consists of:

- **Apache Kafka** for real-time data ingestion  
- **Apache Spark** for streaming analytics and anomaly detection  
- **Apache Airflow** for orchestration and scheduling  
- **Amazon S3** for storage of results  
- **Amazon DynamoDB** for maintaining state to avoid duplicate records  

The pipeline is designed to handle continuous data streams (e.g., IoT sensor readings) and flag anomalies in real-time, leveraging the strengths of each component for a scalable and reliable solution.

> **Note:** The streaming source is treated as a real-time feed. Notebooks (`.ipynb`) contain the Spark logic and are intentionally not included here

---

## Architecture



---

## Component Responsibilities

### Apache Kafka — Ingestion Layer
- High-throughput, durable event log for real-time ingestion.
- Decouples producers from consumers; supports replay via offsets.
- Hosted on a dedicated EC2 instance in this deployment.

### Apache Spark — Streaming & Anomaly Detection
- Structured Streaming job subscribes to the Kafka topic and performs anomaly detection (thresholds/ML) in micro-batches.
- Writes anomaly results to Amazon S3.
- Performs idempotent writes by checking DynamoDB for already-processed event keys before persisting.

### Apache Airflow — Orchestration
- Runs on a separate EC2 instance; schedules and/or triggers the Spark streaming job.
- Provides observability (task logs, retries, alerts) and a central control plane for the pipeline.

### Amazon S3 — Storage
- Durable, cost-efficient data lake sink for anomaly outputs (e.g., JSON/Parquet).
- Organize by date and job to support downstream analytics and lifecycle policies.

### Amazon DynamoDB — Deduplication State
- Key-value table for deduplication (tracks processed event IDs/keys).
- Ensures each anomaly record is written exactly once to S3 even with retries/reprocessing.

---

## Deployment Topology

- **EC2 #1** – Kafka Broker, Spark + Jupyter (driver/notebook)  
- **EC2 #2** – Airflow (scheduler + webserver)
  
<img src="/screensots/EC@.png" alt="NLP6">

Ensure security groups and networking allow Spark to reach Kafka (port 9092), and your client can reach Airflow Web UI (port 8080).

---

## Prerequisites & IAM

### Networking & Security Groups
Open only what you need (**principle of least privilege**):

- **Kafka EC2:** TCP 9092 (from Spark EC2 security group), 22 for SSH (from your IP).  
- **Spark EC2:** TCP 8888 (Jupyter, optional from your IP), 22 SSH, outbound to Kafka:9092, S3/DynamoDB endpoints.  
- **Airflow EC2:** TCP 8080 (Airflow UI from your IP), 22 SSH.  

### IAM Permissions (attach to Spark EC2 role)
Minimum policy capabilities:

- **S3:** `s3:PutObject`, `s3:PutObjectAcl`, `s3:ListBucket`, `s3:GetObject` on the output bucket/prefix.  
- **DynamoDB:** `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:DescribeTable` on the dedup table.  
- **(Optional)** CloudWatch Logs for driver/executor logs.

**Replace placeholders before running:**
- `S3_OUTPUT_BUCKET`: e.g., `s3://serverless-anomaly-detection/anomalies/`  
- `DDB_TABLE`: e.g., `anomaly_dedup_keys`  
- `KAFKA_BOOTSTRAP`: e.g., `kafka-ec2-private-ip:9092`  
- `KAFKA_TOPIC`: e.g., `iot-anomaly`  

---

## Runbook

### 1) Kafka (EC2 #1)
```bash
# (If your Kafka requires ZooKeeper)
$KAFKA_HOME/bin/zookeeper-server-start.sh -daemon $KAFKA_HOME/config/zookeeper.properties

# Start Kafka broker
$KAFKA_HOME/bin/kafka-server-start.sh -daemon $KAFKA_HOME/config/server.properties

# Create topic (idempotent)
$KAFKA_HOME/bin/kafka-topics.sh \
  --bootstrap-server $KAFKA_BOOTSTRAP \
  --create --if-not-exists \
  --topic $KAFKA_TOPIC \
  --partitions 1 --replication-factor 1

# Verify broker/topics
$KAFKA_HOME/bin/kafka-topics.sh --bootstrap-server $KAFKA_BOOTSTRAP --list
```
<img src="/screensots/producer .png" alt="NLP6">

### 2) Spark Streaming & Jupyter

The Spark logic lives in your `.ipynb` notebooks (e.g., `AnomalyDetectionSpark.ipynb`).  
Use the notebook to start the Structured Streaming job that reads from Kafka, checks DynamoDB for duplicates, and writes anomalies to S3.

```bash
# Launch Jupyter (optionally in a tmux/screen session)
jupyter notebook --no-browser --port 8888

# (Optional) SSH tunnel from your laptop:
ssh -i YOUR_KEY.pem -N -L 8888:localhost:8888 ec2-user@<SPARK_EC2_PUBLIC_IP>
# Then open http://localhost:8888 in your browser
```
<img src="/screensots/consumer.png" alt="NLP6">

#### Notebook Configuration (set before running the job):
KAFKA_BOOTSTRAP (e.g., 10.0.1.10:9092)

KAFKA_TOPIC (e.g., iot-anomaly)

S3_OUTPUT_BUCKET (e.g., s3://serverless-anomaly-detection/anomalies/)

### DDB_TABLE (e.g., anomaly_dedup_keys)
**Operational Notes:**
- The streaming job runs continuously; stop manually when needed.
- Use a `checkpointLocation` in S3/EC2 storage to preserve offsets and ensure recoverability.

---

### 3) Airflow Orchestration (EC2 #2)

Airflow coordinates job starts/monitoring.

```bash
# Activate your Airflow environment (if using a venv)
source ~/airflow_venv/bin/activate
export AIRFLOW_HOME=~/airflow

# Start the scheduler (window 1)
airflow scheduler

# Start the webserver (window 2)
airflow webserver --port 8080

# Place DAGs in:
$AIRFLOW_HOME/dags/

# Access the UI at:
http://<AIRFLOW_EC2_PUBLIC_IP>:8080
```
<img src="/screensots/DAG.png" alt="NLP6">
## Data Model & Idempotency

### Deduplication with DynamoDB
- Partition key uniquely identifies an anomaly (e.g., `device_id#timestamp` or a stable event UUID).
- Spark checks `GetItem` before writing to S3; on first encounter it writes to S3 and then `PutItem`s the key into DynamoDB.

### S3 Output Layout (Example)

```text
s3://serverless-anomaly-detection/anomalies/
└── dt=YYYY-MM-DD/
    └── hr=HH/
        ├── part-00000-*.json
        ├── part-00001-*.json
        └── _SUCCESS
```

---

## Operations & Monitoring

- **Kafka:** Monitor broker logs, topic lag, and consumer group offsets.
- **Spark:** Use Spark UI for batch/streaming metrics; ship driver logs to CloudWatch.
- **Airflow:** DAG/task logs, retries, SLA/missed runs; add on-failure alerts.
- **S3:** Configure lifecycle policies (e.g., transition to Glacier after N days).
- **DynamoDB:** Monitor throttling and enable TTL on dedup keys if appropriate.

---

## Validation Checklist

- Kafka broker healthy, topic exists, producer sending events.
- Spark notebook connected to Kafka (`$KAFKA_TOPIC`).
- DynamoDB table reachable; `GetItem/PutItem` working; keys unique.
- Anomaly outputs landing in S3 under the expected prefix.
- Airflow DAG visible, unpaused, and able to trigger/monitor jobs.
- IAM permissions in place; least privilege verified.

---

## Troubleshooting

- **No data in Spark:** Verify Kafka bootstrap host/port reachability and security groups; check topic name.
- **Duplicates in S3:** Confirm DynamoDB `Get/Put` logic is executed before writing; use a stronger key.
- **Airflow DAG not visible:** Ensure file is in `$AIRFLOW_HOME/dags/`, webserver & scheduler running, and no syntax errors.
- **Access denied to S3/DDB:** Check EC2 instance role policies and bucket/table resource ARNs.

---
    



---

## Future Enhancements

- Replace threshold rules with an Isolation Forest or streaming ML (e.g., incremental models).
- Use Delta Lake/Hudi/Iceberg on S3 for ACID and time travel.
- Add a metrics sink (e.g., Prometheus/Grafana) for anomaly rates and SLIs/SLOs.
- Introduce schema management (e.g., Confluent Schema Registry) for Kafka topics.
- High availability with multi-broker Kafka, multi-AZ spread, and checkpointing to S3/EBS.

