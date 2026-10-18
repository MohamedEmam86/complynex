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

import sqlite3
import os

DB_PATH = 'complynex_cms.db'

REQUIRED_POLICIES = [
    {
        "name_en": "AML/CFT Policy",
        "name_ar": "سياسة مكافحة غسل الأموال وتمويل الإرهاب",
        "ref": "CBE AML Law 80/2002, Law 88/2003",
        "desc_en": "Mandatory policy for Anti-Money Laundering and Counter-Terrorist Financing compliance.",
        "desc_ar": "سياسة إلزامية للامتثال لمكافحة غسل الأموال ومكافحة تمويل الإرهاب."
    },
    {
        "name_en": "Customer Protection Policy",
        "name_ar": "سياسة حماية حقوق العملاء",
        "ref": "CBE Consumer Protection Regulations 2019",
        "desc_en": "Policy outlining consumer rights, complaint handling, and transparency.",
        "desc_ar": "سياسة توضح حقوق المستهلك والتعامل مع الشكاوى والشفافية."
    },
    {
        "name_en": "Data Protection & Privacy Policy",
        "name_ar": "سياسة حماية البيانات والخصوصية",
        "ref": "PDPL Law 151/2020",
        "desc_en": "Compliance with the Personal Data Protection Law regarding data handling and subject rights.",
        "desc_ar": "الامتثال لقانون حماية البيانات الشخصية فيما يتعلق بمعالجة البيانات وحقوق أصحاب البيانات."
    },
    {
        "name_en": "Information Security Policy",
        "name_ar": "سياسة أمن المعلومات",
        "ref": "CBE Cybersecurity Framework",
        "desc_en": "Core policy defining the organization's approach to information security.",
        "desc_ar": "السياسة الأساسية التي تحدد نهج المنظمة تجاه أمن المعلومات."
    },
    {
        "name_en": "Business Continuity Management Policy",
        "name_ar": "سياسة إدارة استمرارية الأعمال",
        "ref": "CBE Business Continuity Regulations",
        "desc_en": "Framework for ensuring operations continue during disruptions.",
        "desc_ar": "إطار عمل لضمان استمرار العمليات أثناء الانقطاعات."
    },
    {
        "name_en": "Outsourcing Policy",
        "name_ar": "سياسة التعهيد",
        "ref": "CBE Outsourcing Regulations",
        "desc_en": "Guidelines for managing third-party service providers and outsourcing risks.",
        "desc_ar": "إرشادات لإدارة مقدمي الخدمات من الأطراف الثالثة ومخاطر التعهيد."
    },
    {
        "name_en": "Code of Business Conduct & Ethics",
        "name_ar": "مدونة قواعد السلوك والأخلاقيات",
        "ref": "CBE Governance Regulations",
        "desc_en": "Standards of behavior for employees and management.",
        "desc_ar": "معايير السلوك للموظفين والإدارة."
    },
    {
        "name_en": "Whistleblowing Policy",
        "name_ar": "سياسة الإبلاغ عن المخالفات",
        "ref": "CBE Governance Regulations, FRA",
        "desc_en": "Mechanism for reporting misconduct and protection for whistleblowers.",
        "desc_ar": "آلية للإبلاغ عن سوء السلوك وحماية المبلغين."
    },
    {
        "name_en": "Conflict of Interest Policy",
        "name_ar": "سياسة تضارب المصالح",
        "ref": "CBE Governance Regulations",
        "desc_en": "Procedures to identify and manage conflicts of interest.",
        "desc_ar": "إجراءات لتحديد وإدارة تضارب المصالح."
    },
    {
        "name_en": "Enterprise Risk Management Policy",
        "name_ar": "سياسة إدارة المخاطر المؤسسية",
        "ref": "CBE Risk Management Regulations",
        "desc_en": "Framework for identifying, assessing, and mitigating risks.",
        "desc_ar": "إطار عمل لتحديد وتقييم وتخفيف المخاطر."
    },
    {
        "name_en": "Internal Audit Charter",
        "name_ar": "ميثاق التدقيق الداخلي",
        "ref": "CBE Governance Regulations",
        "desc_en": "Defines the purpose, authority, and responsibility of the internal audit function.",
        "desc_ar": "يحدد الغرض والسلطة والمسؤولية لوظيفة التدقيق الداخلي."
    },
    {
        "name_en": "Cybersecurity Incident Management Policy",
        "name_ar": "سياسة إدارة حوادث الأمن السيبراني",
        "ref": "CBE Cybersecurity Framework",
        "desc_en": "Procedures for detecting, responding to, and recovering from cyber incidents.",
        "desc_ar": "إجراءات لكشف حوادث الأمن السيبراني والاستجابة لها والتعافي منها."
    },
    {
        "name_en": "Access Control Policy",
        "name_ar": "سياسة التحكم في الوصول",
        "ref": "CBE Cybersecurity Framework",
        "desc_en": "Rules for granting and managing access to information systems.",
        "desc_ar": "قواعد منح وإدارة الوصول إلى نظم المعلومات."
    },
    {
        "name_en": "Acceptable Use Policy",
        "name_ar": "سياسة الاستخدام المقبول",
        "ref": "Internal/Best Practice",
        "desc_en": "Guidelines for the appropriate use of company IT assets.",
        "desc_ar": "إرشادات للاستخدام المناسب لأصول تكنولوجيا المعلومات الخاصة بالشركة."
    },
    {
        "name_en": "Vendor Management Policy",
        "name_ar": "سياسة إدارة الموردين",
        "ref": "CBE Outsourcing Regulations",
        "desc_en": "Framework for assessing and managing vendor risks and performance.",
        "desc_ar": "إطار عمل لتقييم وإدارة مخاطر وأداء الموردين."
    },
    {
        "name_en": "Compliance Policy",
        "name_ar": "سياسة الالتزام",
        "ref": "CBE Compliance Regulations",
        "desc_en": "Framework for the compliance function and regulatory adherence.",
        "desc_ar": "إطار عمل لوظيفة الالتزام والامتثال التنظيمي."
    },
    {
        "name_en": "Remuneration Policy",
        "name_ar": "سياسة المكافآت",
        "ref": "CBE Governance Regulations",
        "desc_en": "Guidelines for compensation of board members and senior management.",
        "desc_ar": "إرشادات لتعويض أعضاء مجلس الإدارة والإدارة العليا."
    },
    {
        "name_en": "Succession Planning Policy",
        "name_ar": "سياسة تعاقب الموظفين",
        "ref": "CBE Governance Regulations",
        "desc_en": "Plan for ensuring continuity of key leadership roles.",
        "desc_ar": "خطة لضمان استمرارية الأدوار القيادية الرئيسية."
    }
]

def restore_policies():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    print(f"Connecting to {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create Table if not exists
    print("Ensuring 'required_policies' table exists...")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS required_policies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            policy_name_en VARCHAR(200) NOT NULL,
            policy_name_ar VARCHAR(200),
            regulatory_reference VARCHAR(200),
            is_mandatory BOOLEAN DEFAULT 1,
            description_en TEXT,
            description_ar TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_required_policies_name ON required_policies(policy_name_en)")
    
    # Check existing count
    count = cursor.execute("SELECT COUNT(*) FROM required_policies").fetchone()[0]
    print(f"Current required policies count: {count}")
    
    if count == 0:
        print("Populating default required policies...")
        for p in REQUIRED_POLICIES:
            cursor.execute('''
                INSERT INTO required_policies (policy_name_en, policy_name_ar, regulatory_reference, is_mandatory, description_en, description_ar)
                VALUES (?, ?, ?, 1, ?, ?)
            ''', (p['name_en'], p['name_ar'], p['ref'], p['desc_en'], p['desc_ar']))
        print(f"Inserted {len(REQUIRED_POLICIES)} policies.")
    else:
        print("Table already has data. Skipping insertion.")
        
    conn.commit()
    conn.close()
    print("Done.")

if __name__ == "__main__":
    restore_policies()
