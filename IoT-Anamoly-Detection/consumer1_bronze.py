# now spark consumer code 

# bronze_stream.py
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, to_timestamp, to_date, date_format

BOOTSTRAP = "localhost:9094"
TOPIC = "iot_raw"

OUT = "s3a://iot-anomaly-detection/bronze/iot_events/"
CHK = "s3a://iot-anomaly-detection/checkpoints/bronze/"

spark = SparkSession.builder.appName("IoTBronze").getOrCreate()
spark.sparkContext.setLogLevel("WARN")

raw = (spark.readStream.format("kafka")
       .option("kafka.bootstrap.servers", BOOTSTRAP)
       .option("subscribe", TOPIC)
       .option("startingOffsets", "latest")
       .load())

### we dont use schema becuse its raw bronze we save everything how the come from producer

bronze = (raw.selectExpr("CAST(value AS STRING) AS json", "timestamp")
          .withColumn("ingestion_ts", to_timestamp(date_format(col("timestamp"), "yyyy-MM-dd HH:mm:ss")))
          .withColumn("ingestion_date", to_date(col("ingestion_ts")))
          .withColumn("hour", date_format(col("ingestion_ts"), "HH")))

(bronze.writeStream
   .format("json")
   .option("path", OUT)
   .option("checkpointLocation", CHK)
   .partitionBy("ingestion_date","hour")
   .outputMode("append")
   .trigger(processingTime="60 seconds")
   .start()
   .awaitTermination())