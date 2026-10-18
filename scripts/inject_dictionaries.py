# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
#
# This software is the proprietary and confidential intellectual property of
# ComplyNex (complynex.online), owned by Mohamed Emam.
# Unauthorized copying, reproduction, modification,
# distribution, reverse engineering, or use of this software, in whole or in
# part, via any medium, is strictly prohibited without prior written
# permission from the owner.
#
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# Contact: f.mohemam85@gmail.com | admin@complynex.online
#
# Registered deployment: complynex.online
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================

import os, re

lines = open('Phase4_Tables.txt', encoding='utf-8').readlines()
new_entries = []
# Lines 17 to 41 contain the 25 variants
for line in lines[16:42]:
    if '|' in line and 'Arabic equivalent' not in line:
        english_part, arabic_part = line.split('|')
        arabic_key = arabic_part.strip()
        english_list = [e.strip().lower() for e in english_part.split('/')]
        new_entries.append(f"    '{arabic_key}': {english_list},")

entries_str = '\n'.join(new_entries)

engine_path = 'screening/complynex_engine.py'
utils_path = 'screening/arabic_utils.py'

# 1. Update complynex_engine.py
with open(engine_path, 'r', encoding='utf-8') as f:
    engine_content = f.read()
    
insert_pos = engine_content.find("    # مصطفى variants")
if insert_pos > 0:
    engine_content = engine_content[:insert_pos] + "    # Phase 4 Egyptian Additions\n" + entries_str + "\n\n" + engine_content[insert_pos:]
    with open(engine_path, 'w', encoding='utf-8') as f:
        f.write(engine_content)
    print("Updated complynex_engine.py dict")
else:
    print("Failed to find insert point in complynex_engine")

# 2. Update arabic_utils.py
with open(utils_path, 'r', encoding='utf-8') as f:
    utils_content = f.read()

insert_pos_utils = utils_content.find("    # Common Egyptian Names")
if insert_pos_utils > 0:
    utils_content = utils_content[:insert_pos_utils] + "    # Phase 4 Egyptian Additions\n" + entries_str + "\n\n" + utils_content[insert_pos_utils:]
    with open(utils_path, 'w', encoding='utf-8') as f:
        f.write(utils_content)
    print("Updated arabic_utils.py dict")
else:
    print("Failed to find insert point in arabic_utils")
