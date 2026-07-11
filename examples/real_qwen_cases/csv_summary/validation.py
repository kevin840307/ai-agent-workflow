from pathlib import Path
import csv_summary
sample = Path("sample.csv")
sample.write_text("name,amount\na,10\nb,\nc,2.5\n", encoding="utf-8")
result = csv_summary.summarize(sample)
assert result["rows"] == 3, result
assert abs(result["amount_total"] - 12.5) < 1e-9, result
print("VALIDATION PASS: csv_summary")
