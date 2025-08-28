# silver_stream.py
import boto3, os, json, math
from botocore.exceptions import ClientError

from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col, from_json, to_timestamp, window, when, lit,
    concat_ws, date_format
)
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, TimestampType

AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-2")
SILVER_BASE = "s3a://iot-anomaly-detection/silver/iot_events/"
SILVER_CHECKPOINT = "s3a://iot-anomaly-detection/checkpoints/silver/"
BRONZE_BASE = "s3a://iot-anomaly-detection/bronze/iot_events/"
DDB_TABLE = "iot_dedup"
SNS_TOPIC_ARN = "arn:aws:sns:us-east-2:YOUR_ACCOUNT_ID:iot-anomaly-alerts"

spark = (
    SparkSession.builder.appName("IoTSilver")
    .config("spark.sql.shuffle.partitions", "1")
    .getOrCreate()
)

schema = StructType([
    StructField("device_id", StringType(), False),
    StructField("ts", StringType(), False),          
    StructField("metric", StringType(), False),         
    StructField("value", DoubleType(), False),
    StructField("site", StringType(), False)
])

# Read Bronze JSON lines as stream (autoloader-like simple file stream)
df_raw = (
    spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "json")
        .option("cloudFiles.inferColumnTypes", "false")
        .load(BRONZE_BASE)
)

df = (
    df_raw.select(from_json(col("json"), schema).alias("e"))
          .select("e.*")
          .withColumn("event_ts", to_timestamp(col("ts")))
          .withColumn("pk", concat_ws("#", col("device_id"), date_format(col("event_ts"), "yyyy-MM-dd'T'HH:mm:ss'Z'")))
)

# Simple anomaly rule by metric
df = df.withColumn(
    "is_anomaly",
    when((col("metric") == lit("temp_c")) & ((col("value") < lit(-10)) | (col("value") > lit(60))), lit(True))
    .when((col("metric") == lit("vibration_mm_s")) & (col("value") > lit(25)), lit(True))
    .otherwise(lit(False))
)

df = df.withColumn("event_date", col("event_ts").cast("date"))

def foreach_batch(batch_df, batch_id: int):
    if batch_df.rdd.isEmpty():
        return

    # Collect keys to check in DynamoDB (cap to reasonable chunk sizes)
    keys = [r["pk"] for r in batch_df.select("pk").distinct().collect()]
    if not keys:
        return

    ddb = boto3.client("dynamodb", region_name=AWS_REGION)
    sns = boto3.client("sns", region_name=AWS_REGION)

    # BatchGetItem in chunks of 100
    existing = set()
    CHUNK=100
    for i in range(0, len(keys), CHUNK):
        chunk = keys[i:i+CHUNK]
        resp = ddb.batch_get_item(
            RequestItems={
                DDB_TABLE: { "Keys": [{"pk": {"S": k}} for k in chunk] }
            }
        )
        items = resp.get("Responses", {}).get(DDB_TABLE, [])
        for it in items:
            existing.add(it["pk"]["S"])

    # Filter out duplicates
    new_df = batch_df.filter(~col("pk").isin(list(existing)))
    if new_df.rdd.isEmpty():
        return

    # Write new rows to Silver (partitioned)
    (new_df
     .select("device_id","event_ts","metric","value","site","is_anomaly","event_date")
     .write
     .mode("append")
     .partitionBy("metric","site","event_date")
     .format("parquet")
     .save(SILVER_BASE)
    )

    # Write keys to DynamoDB with conditional put (idempotent)
    for r in new_df.select("pk").distinct().collect():
        pk = r["pk"]
        try:
            ddb.put_item(
                TableName=DDB_TABLE,
                Item={"pk": {"S": pk}},
                ConditionExpression="attribute_not_exists(pk)"
            )
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise

    # If anomalies exist in this batch, send a quick SNS alert (summary)
    count_anom = new_df.filter(col("is_anomaly") == True).count()
    if count_anom > 0:
        msg = f"[IoT Silver] Detected {count_anom} anomalies in batch {batch_id}."
        sns.publish(TopicArn=SNS_TOPIC_ARN, Message=msg, Subject="IoT Anomaly Detected")

query = (
    df.writeStream
      .foreachBatch(foreach_batch)
      .option("checkpointLocation", SILVER_CHECKPOINT)
      .start()
)

query.awaitTermination()
