import pandas as pd

df = pd.read_csv("employees.csv")
for i, row in df.iterrows():
    if row["salary"] == "TBD":
        continue
print(df.head())
