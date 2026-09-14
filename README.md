python -m src.naver_food_to_sheets
python -m src.naver_food_to_sheets 2026-09-13

powershell -Command "$d=Get-Date '2025-01-01'; $e=Get-Date '2025-12-31'; while($d -le $e){ python -m src.naver_food_to_sheets $d.ToString('yyyy-MM-dd'); if($LASTEXITCODE -ne 0){break}; $d=$d.AddDays(1)}"

