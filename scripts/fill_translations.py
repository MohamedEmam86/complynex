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

import os
import re

po_file_path = "C:\\Users\\Dina\\Downloads\\Kimi_Agent_Complynexpay Compliance Gem Design\\complynex_cms\\translations\\ar\\LC_MESSAGES\\messages.po"

with open(po_file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
current_msgid = None
msgid_line_index = -1

i = 0
count = 0
while i < len(lines):
    line = lines[i]
    
    if line.startswith('msgid "'):
        current_msgid = line.strip()[7:-1]
        new_lines.append(line)
        i += 1
        # Handle multiline msgid
        while i < len(lines) and lines[i].startswith('"'):
             current_msgid += lines[i].strip()[1:-1]
             new_lines.append(lines[i])
             i += 1
        continue
        
    if line.startswith('msgstr ""'):
        if current_msgid:
            # Check if it's not empty string (header)
            if current_msgid:
                new_line = f'msgstr "[AR] {current_msgid}"\n'
                new_lines.append(new_line)
                count += 1
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
        i += 1
        continue
        
    new_lines.append(line)
    i += 1

with open(po_file_path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print(f"Filled {count} untranslated strings.")
