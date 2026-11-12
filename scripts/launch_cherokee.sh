#!/bin/bash
cd ~/foreclosure-scraper
export DISPLAY=:99
export PYTHONUNBUFFERED=1
export PYTHONPATH=src:.venv/lib/python3.12/site-packages
export CHEROKEE_SC_PASSWORD="${1}"
.venv/bin/python3.12 scripts/run_cherokee_production.py > /tmp/cherokee_prod2.log 2>&1
