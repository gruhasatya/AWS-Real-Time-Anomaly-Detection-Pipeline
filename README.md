#  IOT- Anomaly-Detection-pipeline

### steps to follow not accurate but follow structure add your options to it and expand the project 

## why needed?

### Just to keep track of things which require temperature tracking instead an easy setup not mentioned about iot device thats totally different subject justed wanted to keep the background use your ideas with it

1. Update packages → `sudo dnf update -y`
2. Install + enable Docker → `sudo dnf install -y docker && sudo systemctl enable --now docker`
3. Add user to docker group → `sudo usermod -aG docker ec2-user && newgrp docker`
4. Verify Docker + install docker-compose → `docker ps && curl -SL .../v2.27.0/docker-compose-linux-x86_64 -o /usr/local/bin/docker-compose && chmod +x /usr/local/bin/docker-compose && docker-compose version`
5. Setup Kafka (KRaft) → `mkdir -p ~/iot-pipeline && cd ~/iot-pipeline && nano docker-compose.yml && docker-compose up -d`
6. Create Kafka topic → `docker exec -it kafka kafka-topics.sh --create --topic iot_raw --bootstrap-server localhost:9092 --partitions 1 --replication-factor 1 && docker exec -it kafka kafka-topics.sh --list --bootstrap-server localhost:9092`
7. Python producer (synthetic IoT) → `python3 -m venv venv && source venv/bin/activate && pip install kafka-python requests && nano iot_producer.py && python iot_producer.py`
8. Sanity consume Kafka msgs → `docker exec -it kafka kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic iot_raw --from-beginning --max-messages 5`
9. Bronze stream (Kafka → S3 JSONL) → `nano bronze_stream.py && docker run --rm -it --network host -v "$PWD":/app -e AWS_DEFAULT_REGION=us-east-2 bitnami/spark:3.5.2 ... spark-submit /app/bronze_stream.py` → lands **`s3://iot-anomaly-detection/bronze/iot_events/`**
10. Silver transform (clean + dedup) → land curated Parquet/Delta to **`s3://iot-anomaly-detection/silver/iot_events/`**
11. **Feature engineering (for ML)** → compute rolling stats (e.g., mean/std/EMA, last_n deltas) into **`s3://iot-anomaly-detection/silver/iot_features/`**
12. **Train ML model (IsolationForest)** → `python3 -m venv venv && source venv/bin/activate && pip install scikit-learn pandas numpy joblib boto3 && nano train_anomaly_model.py && python train_anomaly_model.py` → save model to **`s3://iot-anomaly-detection/models/iot_anomaly_iforest.joblib`**
13. Gold aggregates (analytics-ready) → KPIs + anomaly counts to **`s3://iot-anomaly-detection/gold/iot_aggregates/`**; anomalies table to **`s3://iot-anomaly-detection/gold/iot_anomalies/`**
14. Athena setup → set results bucket, then `CREATE DATABASE IF NOT EXISTS iot_pipeline;` (create external tables for Silver features + Gold aggregates/anomalies)
15. DynamoDB table (dedup) → create **iot_dedup** with partition key **pk** (String)
16. SNS topic (alerts) → create **iot-anomaly-alerts** + confirm email subscription
17. Airflow services → add Airflow to `docker-compose.yml` (webserver + scheduler, mount `./dags`), then `docker-compose up -d airflow-webserver airflow-scheduler`
18. **Airflow DAG (3 tasks)** → **Repair Partitions** (MSCK/Glue on Silver/Gold) → **Anomaly Check (ML)** (load model from `s3://.../models/iot_anomaly_iforest.joblib`, score latest Silver features, write hits to Gold `iot_anomalies/`) → **Notify** (publish summary to SNS `iot-anomaly-alerts`)
19. Trigger & monitor DAG → open Airflow UI (`http://localhost:8080`), run DAG, verify SNS email + new files in `gold/iot_anomalies/`
20. Validate Kafka anytime → `docker exec -it kafka kafka-topics.sh --list --bootstrap-server localhost:9092`
