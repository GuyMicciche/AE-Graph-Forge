#!/usr/bin/env python3
"""AE Graph Forge launcher.  Usage:  python run.py [data.csv]"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aegraphforge.app import main
raise SystemExit(main())
