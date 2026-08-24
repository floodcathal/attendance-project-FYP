"""Seed InfluxDB with six weeks of synthetic attendance data.

Reads connection details from the environment (see .env.example):
    INFLUXDB_API_TOKEN, INFLUXDB_ORG, INFLUXDB_BUCKET, INFLUXDB_URL
"""
import os
import random
import sys
from datetime import datetime, timedelta

import requests

INFLUX_URL    = os.environ.get("INFLUXDB_URL", "http://localhost:8086")
INFLUX_TOKEN  = os.environ.get("INFLUXDB_API_TOKEN")
INFLUX_ORG    = os.environ.get("INFLUXDB_ORG", "myorg")
INFLUX_BUCKET = os.environ.get("INFLUXDB_BUCKET", "attendance")

if not INFLUX_TOKEN:
    sys.exit("INFLUXDB_API_TOKEN is not set. Copy .env.example to .env and fill it in.")

# Generate hundreds of students (e.g., 500 students)
STUDENTS = [f"C22{random.randint(1000000, 9999999)}" for _ in range(500)]

# Define Buildings and Floors
BUILDINGS = {
    "TMain": "TM",
    "TNorth": "TN",
    "CQ": "CQ",
    "EQ": "EQ"
}
FLOORS = ["0", "1", "2", "3"]

ROOMS = {}
for b_name, b_prefix in BUILDINGS.items():
    for floor in FLOORS:
        # Create 3 rooms per floor for each building
        for r_num in range(1, 4):
            room_id = f"{b_prefix}{floor}{r_num:02d}"
            ROOMS[room_id] = {
                "building": b_name,
                "floor": floor,
                "capacity": random.choice([30, 40, 50, 100])
            }

HOURLY_WEIGHTS = [0,0,0,0,0,0,0,1,3,9,10,9,4,3,9,10,7,5,2,1,0,0,0,0]

def write_lines(lines):
    payload = "\n".join(lines)
    try:
        r = requests.post(
            f"{INFLUX_URL}/api/v2/write",
            params={"org": INFLUX_ORG, "bucket": INFLUX_BUCKET, "precision": "s"},
            headers={"Authorization": f"Token {INFLUX_TOKEN}", "Content-Type": "text/plain; charset=utf-8"},
            data=payload,
        )
        return r.status_code
    except Exception as e:
        return f"Error: {e}"

def pick_hour():
    return random.choices(range(24), weights=HOURLY_WEIGHTS, k=1)[0]

now = datetime.utcnow()
lines = []

print(f"Generating 6 weeks of historical data for {len(STUDENTS)} students across {len(ROOMS)} rooms...")
for day_offset in range(42):
    day = now - timedelta(days=day_offset)
    is_weekend = day.weekday() >= 5
    multiplier = 0.15 if is_weekend else 1.0
    
    for room_id, info in ROOMS.items():
        # Scale number of students per room based on capacity
        n = int(random.randint(5, info['capacity'] // 2) * multiplier)
        for student in random.sample(STUDENTS, min(n, len(STUDENTS))):
            hour = pick_hour()
            dt = day.replace(hour=hour, minute=random.randint(0,59), second=random.randint(0,59))
            if dt > now:
                continue
            ts = int(dt.timestamp())
            lines.append(f"attendance_events,studentId={student},roomId={room_id},building={info['building']},floor={info['floor']},action=check-in value=1 {ts}")
            
            # Stay duration between 30 and 180 minutes
            out_dt = dt + timedelta(minutes=random.randint(30, 180))
            if out_dt < now:
                ts2 = int(out_dt.timestamp())
                lines.append(f"attendance_events,studentId={student},roomId={room_id},building={info['building']},floor={info['floor']},action=check-out value=1 {ts2}")

print("Generating current occupancy...")
# Randomly populate rooms for current occupancy
for room_id, info in ROOMS.items():
    occupancy_count = random.randint(0, info['capacity'] // 2)
    for student in random.sample(STUDENTS, min(occupancy_count, len(STUDENTS))):
        dt = now - timedelta(minutes=random.randint(5, 120))
        ts = int(dt.timestamp())
        lines.append(f"attendance_events,studentId={student},roomId={room_id},building={info['building']},floor={info['floor']},action=check-in value=1 {ts}")

print("Generating recent activity table rows...")
for _ in range(100): # Increased recent activity
    student = random.choice(STUDENTS)
    room_id = random.choice(list(ROOMS.keys()))
    info = ROOMS[room_id]
    action = random.choice(["check-in","check-out"])
    dt = now - timedelta(minutes=random.randint(1, 60))
    ts = int(dt.timestamp())
    lines.append(f"attendance_events,studentId={student},roomId={room_id},building={info['building']},floor={info['floor']},action={action} value=1 {ts}")

print(f"Total entries: {len(lines)}. Writing to InfluxDB...")
BATCH = 1000 # Increased batch size for efficiency
for i in range(0, len(lines), BATCH):
    batch = lines[i:i+BATCH]
    status = write_lines(batch)
    print(f"  Batch {i//BATCH + 1} — HTTP {status}")

print("Done.")
