########################### new project code 

from kafka import KafkaProducer
import json, time, random, datetime

producer = KafkaProducer(
    bootstrap_servers=['localhost:9094'],
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

TOPIC = "iot_raw"
DEVICES = [f"dev-{i:03d}" for i in range(1, 6)]

# while True:   # just unhastag it just for spark clear code
    for d in DEVICES:
        value = 25 + random.uniform(-2, 2)  # baseline temp with noise
        # inject anomaly ~1% chance
        if random.random() < 0.01:
            value += random.choice([10, -10])

        event = {
            "device_id": d,
            "ts": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "metric": "temp_c",
            "value": round(value, 2),
            "site": "plant-a"
        }

        producer.send(TOPIC, event)
        print("Sent:", event)
        producer.flush()
        time.sleep(2)