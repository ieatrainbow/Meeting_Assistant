# -*- coding: utf-8 -*-
"""Живой прогон клиента Outlook: какая встреча будет выбрана сейчас."""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from outlook_client import get_current_or_next_meeting_details

d = get_current_or_next_meeting_details(log_callback=lambda s: print(s))
if d:
    print("RESULT:", d["subject"], "| start =", d["start"])
else:
    print("RESULT: None")
