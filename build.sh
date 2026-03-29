#!/bin/bash
python -m nuitka --standalone --onefile \
  --output-filename=qaclan \
  --output-dir=dist \
  --include-package=rich._unicode_data \
  --include-data-dir=web/static=web/static \
  qaclan.py
