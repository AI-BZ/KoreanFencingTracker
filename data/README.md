# Data Directory

This folder contains scraped fencing data (JSON files).
Files are excluded from git due to large size.

Run scraper to generate:
```bash
arch -arm64 python3 -m scraper.full_scraper --status "종료" --output data/fencing_full_data_v2.json
```
