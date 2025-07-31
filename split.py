# split_csv.py

import os
import pandas as pd

INPUT_DIR = "csv"
CHUNK_DIR = "chunks"
CHUNK_SIZE = 1000

os.makedirs(CHUNK_DIR, exist_ok=True)


input_files = [f for f in os.listdir(INPUT_DIR) if f.endswith(".csv")]

for file in input_files:
    team_name = file.replace(".csv", "")
    df = pd.read_csv(os.path.join(INPUT_DIR, file), encoding="utf-8")
    total_rows = len(df)

    for i in range(0, total_rows, CHUNK_SIZE):
        chunk = df[i:i+CHUNK_SIZE]
        chunk_num = i // CHUNK_SIZE + 1

        out_file = f"{CHUNK_DIR}/{team_name}_part_{chunk_num}.csv"
        chunk.to_csv(out_file, index=False, encoding="utf-8-sig")
        print(f"✅ Saved {out_file} ({len(chunk)} rows)")
