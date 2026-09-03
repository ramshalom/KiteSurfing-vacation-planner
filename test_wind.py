from tools import fetch_wind_data
import json

result = fetch_wind_data("Mui Ne, Vietnam", "01-14", "01-27")
print(json.dumps(result, indent=2))
