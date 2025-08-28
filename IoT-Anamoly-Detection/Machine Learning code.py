import os
import boto3
import joblib
import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
from io import BytesIO


AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-2")
SILVER_PATH = "s3://iot-anomaly-detection/silver/iot_events/"
MODEL_PATH  = "s3://iot-anomaly-detection/models/iot_anomaly_iforest.joblib"
LOCAL_MODEL = "iot_anomaly_iforest.joblib"


print("Downloading sample data from Silver layer...")

s3 = boto3.client("s3", region_name=AWS_REGION)
bucket = "iot-anomaly-detection"
prefix = "silver/iot_events/"

resp = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
files = [c["Key"] for c in resp.get("Contents", []) if c["Key"].endswith(".parquet")]

if not files:
    raise RuntimeError("No parquet files found in Silver S3 path. Run streaming first.")


sample_keys = files[:5]  # first 5 
print(f"Using {len(sample_keys)} parquet files for training.")



import pyarrow.parquet as pq
import s3fs

fs = s3fs.S3FileSystem()

dfs = []
for k in sample_keys:
    with fs.open(f"{bucket}/{k}", "rb") as f:
        table = pq.read_table(f)
        dfs.append(table.to_pandas())

df = pd.concat(dfs, ignore_index=True)

print(f"Loaded {df.shape[0]} rows from Silver")

df = df.dropna(subset=["value"])

df["metric_id"] = df["metric"].astype("category").cat.codes
df["site_id"]   = df["site"].astype("category").cat.codes

X = df[["value", "metric_id", "site_id"]].to_numpy()

print(f"Feature matrix shape: {X.shape}")



print("Training IsolationForest model...")
model = IsolationForest(
    n_estimators=100,
    contamination=0.05,   # Anomalies 
    random_state=42,
)
model.fit(X)

joblib.dump(model, LOCAL_MODEL)
print(f"Model saved locally to {LOCAL_MODEL}")


print(f"Uploading model to {MODEL_PATH}...")
s3 = boto3.client("s3", region_name=AWS_REGION)

with open(LOCAL_MODEL, "rb") as f:
    s3.upload_fileobj(f, bucket, "models/iot_anomaly_iforest.joblib")

print(" Model uploaded to S3 successfully.")
