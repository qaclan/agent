#!/bin/bash
python -m nuitka --standalone --onefile \
  --output-filename=qaclan \
  --output-dir=dist \
  cli.py
