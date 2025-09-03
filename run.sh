#!/bin/bash

# GET ARGUMENTS:
read -p "Enter input file (CSV), output format with --output (CSV (default), Excel), --limit (to scrape only an amount of requests)"

# INSTALL DEPENDENCIES IF NOT INSTALLED
pip install -r requirements.txt

# Run the scraper
python3 scraper.py "$arguments"