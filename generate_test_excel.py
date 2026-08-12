# Test Excel Generator
import pandas as pd

data = {
    "StudentID": ["001234", "000567", "100001", "001234", "100002"],
    "Status": ["PHOTOGRAPHED", " Photographed ", "photographed", "PHOTOGRAPHED", "NOT PHOTOGRAPHED"]
}

df = pd.DataFrame(data)
df.to_excel("test_students.xlsx", index=False)
print("test_students.xlsx created!")
