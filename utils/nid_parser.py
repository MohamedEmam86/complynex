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

def parse_egyptian_nid(nid_str):
    if not nid_str or len(str(nid_str)) != 14 or not str(nid_str).isdigit():
        return None
    try:
        nid = str(nid_str)
        century_digit = nid[0]
        year = int(nid[1:3])
        month = nid[3:5]
        day = nid[5:7]
        
        if century_digit == '2': full_year = 1900 + year
        elif century_digit == '3': full_year = 2000 + year
        else: full_year = 1900 + year
        
        dob_str = f"{full_year}-{month}-{day}"
        gender = 'Male' if int(nid[12]) % 2 != 0 else 'Female'
        
        gov_codes = {
            '01': 'Cairo', '02': 'Alexandria', '03': 'Port Said', '04': 'Suez', 
            '11': 'Dakahlia', '12': 'Damietta', '13': 'Fayoum', '14': 'Gharbia',
            '15': 'Giza', '16': 'Ismailia', '17': 'Menofia', '18': 'Minya',
            '19': 'Qalyubia', '21': 'Sharqia', '22': 'Beheira', '23': 'Beni Suef',
            '24': 'Kafr El Sheikh', '25': 'Matruh', '26': 'Assiut', '27': 'Red Sea',
            '28': 'New Valley', '29': 'Sohag', '31': 'Qena', '32': 'Luxor',
            '33': 'Aswan', '35': 'North Sinai', '36': 'South Sinai', '88': 'Foreign'
        }
        birth_gov = gov_codes.get(nid[7:9], 'Unknown')
        return {'dob': dob_str, 'gender': gender, 'birth_governorate': birth_gov}
    except: return None
