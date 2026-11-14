"""Generate clean multi-page PDF policy documents (POL-005 and POL-009) using fpdf2."""

from pathlib import Path
from fpdf import FPDF

POLICIES_DIR = Path(__file__).resolve().parent.parent / "policies"


class PolicyPDF(FPDF):
    def __init__(self, doc_id: str, title: str):
        super().__init__()
        self.doc_id = doc_id
        self.doc_title = title
        self.set_auto_page_break(auto=True, margin=18)

    def header(self):
        self.set_font("Helvetica", "I", 9)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, f"Northstar Cloud Labs, Inc. | {self.doc_id}: {self.doc_title}", align="L", new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def footer(self):
        self.set_y(-14)
        self.set_font("Helvetica", "I", 9)
        self.set_text_color(110, 110, 110)
        self.cell(0, 8, f"{self.doc_id} - Page {self.page_no()}", align="C")


def _ascii_safe(text: str) -> str:
    return (
        text.replace("\u2014", " - ")
        .replace("\u2013", "-")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )


def write_policy_pdf(filename: str, doc_id: str, title: str, metadata_lines: list[str], sections: list[tuple[str, list[str]]]) -> Path:
    pdf = PolicyPDF(doc_id, _ascii_safe(title))
    pdf.set_margins(18, 18, 18)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(20, 35, 60)
    pdf.multi_cell(pdf.epw, 8, _ascii_safe(f"{doc_id}: {title}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_font("Helvetica", "", 10.5)
    pdf.set_text_color(40, 40, 40)
    for line in metadata_lines:
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(pdf.epw, 6, _ascii_safe(line), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    for heading, paragraphs in sections:
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", "B", 12.5)
        pdf.set_text_color(20, 45, 90)
        pdf.multi_cell(pdf.epw, 7, _ascii_safe(heading), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1.5)

        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(30, 30, 30)
        for p in paragraphs:
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(pdf.epw, 6.2, _ascii_safe(p), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2.5)
        pdf.ln(2)

    out_path = POLICIES_DIR / filename
    pdf.output(str(out_path))
    return out_path


def main():
    POLICIES_DIR.mkdir(parents=True, exist_ok=True)

    pol_005_sections = [
        ("Section 1. Purpose and Zero-Trust Security Scope", [
            "Northstar Cloud Labs, Inc. operates cloud infrastructure handling sensitive customer telemetry, intellectual property, and employee records. This Information Security and Remote Access Policy defines mandatory endpoint protections, authentication controls, network encryption requirements, and international remote work safeguards applicable to all employees, contractors, and interns.",
            "Compliance with this policy is a condition of network access and a strict prerequisite for all remote work or international travel arrangements governed by POL-003 (Remote, Hybrid, and International Work Policy).",
        ]),
        ("Section 2. Endpoint Encryption, MDM, and Hardware MFA", [
            "2.1 Full-Disk Encryption: Every corporate laptop and workstation must run active full-disk encryption (Apple FileVault 2 on macOS or BitLocker with TPM on Windows/Linux) with recovery keys escrowed in Northstar Mobile Device Management (MDM).",
            "2.2 Hardware FIDO2 Multi-Factor Authentication: Passwords alone are never sufficient. Every worker must maintain at least two enrolled hardware FIDO2 security keys (YubiKey) to authenticate to SSO, GitHub, cloud consoles, and HR portals.",
            "2.3 Screen Lock and Physical Security: Devices must automatically lock after 5 minutes of inactivity. Employees may never leave unlocked company laptops unattended in hotel rooms, cafes, airport lounges, or coworking spaces.",
        ]),
        ("Section 3. Network Security, VPN, and Public Wi-Fi Rules", [
            "3.1 Mandatory Corporate VPN: Employees working outside a Northstar physical hub must keep the approved WireGuard corporate VPN active whenever accessing internal repositories, staging environments, ticketing queues, or HR systems.",
            "3.2 Public Wi-Fi Prohibition Without VPN: Connecting directly to untrusted hotel, cafe, or airport Wi-Fi networks without an active corporate VPN tunnel is strictly prohibited. When traveling internationally, employees are strongly advised to tether via encrypted personal mobile hotspots or dedicated travel routers whenever feasible.",
            "3.3 Prohibited Software and Cloud Storage: Unapproved personal cloud drives (personal Dropbox, personal Google Drive), unapproved browser extensions, and unauthorized local AI tools are prohibited for storing or processing company confidential data or customer PII.",
        ]),
        ("Section 4. Security Access Tiers and International Travel Requirements", [
            "Northstar assigns every worker a formal security tier recorded in their employee profile:",
            "- Standard-Corp & Standard-Dev: Standard corporate SaaS and non-production development access. Eligible to travel internationally with their primary encrypted corporate laptop once InfoSec approves the remote work request under POL-003.",
            "- Prod-Admin & Customer-PII: Elevated privileges covering production Kubernetes clusters, AWS/GCP IAM admin roles, or unmasked customer databases. Employees in Prod-Admin or Customer-PII tiers are strictly prohibited from taking their primary workstation across international borders.",
            "- Contractor-Limited: Scoped external contractor access with zero production database access unless granted a time-bounded break-glass exemption.",
            "4.1 Clean Travel Loaner Laptop Requirement: Any Prod-Admin or Customer-PII employee approved for international remote work or international business travel must check out an InfoSec-provisioned Clean Travel Loaner Laptop through IT Operations (POL-008 Section 4) at least 10 business days before departure. Travel loaners operate with temporary least-privilege VPN profiles, wiped local storage, and disabled production root credentials.",
            "4.2 Prohibited Sanctions Jurisdictions: Accessing Northstar systems or transporting corporate hardware into embargoed or high-risk jurisdictions (Russia, Belarus, Iran, North Korea, Syria, Cuba, or mainland China without executive CISO exception) will trigger immediate credential revocation.",
        ]),
        ("Section 5. Incident Reporting and Data Breach Escalation", [
            "5.1 24-Hour Lost/Stolen Device Rule: Lost, stolen, or potentially compromised laptops, mobile phones, or YubiKey tokens must be reported immediately—and no later than 24 hours—to InfoSec (infosec@northstarcloud.example) and IT Operations so MDM remote wipe and session token revocation can be performed.",
            "5.2 Suspected Phishing or Data Exposure: Any suspected phishing compromise or unauthorized exposure of employee or customer PII must be escalated immediately as a Priority P1 incident under POL-011.",
        ]),
        ("Section 6. Data Classification and Generative AI Tool Usage", [
            "6.1 Four-Tier Data Classification: Northstar classifies information into Public, Internal, Confidential, and Restricted (Customer PII & Production Credentials). Restricted data may never be copied to local USB drives, personal laptops, or unapproved third-party tools.",
            "6.2 Acceptable AI Tooling: Employees may only paste Internal or Confidential company data into enterprise-licensed AI services covered by Northstar's zero-data-retention Business Associate / Enterprise DPA agreements. Pasting customer PII, private keys, or production credentials into consumer AI web forms is strictly forbidden.",
            "6.3 International Border Device Inspections: If customs or border officials compel device unlocking during international travel, employees must comply with local law to avoid detention, refrain from resisting physically, and notify InfoSec immediately upon clearing customs so emergency credential rotation can be executed within 1 hour.",
        ]),
    ]

    pol_009_sections = [
        ("Section 1. Purpose and Scope of Protected Leaves", [
            "Northstar Cloud Labs, Inc. supports employees through major family milestones, serious personal or family health events, bereavement, and civic duties. This policy outlines Northstar's Paid Parental Leave, Medical & Family Leave (FMLA / Short-Term Disability coordination), Bereavement Leave, and Jury Duty policies.",
            "This policy operates alongside—and never diminishes—more generous statutory entitlements under applicable US federal/state, Canadian provincial, or UK statutory family leave laws.",
        ]),
        ("Section 2. Paid Parental Leave (16 Weeks at 100% Pay)", [
            "2.1 Tenure and Classification Eligibility: Full-Time Regular Employees (FTEs) who have completed at least 6 months (180 calendar days) of continuous employment on the date of birth, adoption, or foster placement are eligible for 16 consecutive or intermittent weeks (80 business days) of 100% paid Parental Leave.",
            "2.2 Equal Caregiver Parity: Northstar provides 16 weeks identically to all eligible birth parents, non-birth parents, adoptive parents, and foster parents without primary/secondary caregiver distinctions.",
            "2.3 Bonding Window and Notice: Paid Parental Leave must be completed within 12 months of the child's birth or placement. Employees should notify People Operations and their manager at least 30 calendar days in advance (or as soon as practicable for unexpected placements) to coordinate handoff coverage and benefits continuation.",
            "2.4 Employees Under 180 Days Tenure: FTEs with fewer than 180 days of tenure are ineligible for the full 16-week company-paid program (POL-007 Section 3.3), though People Operations coordinates statutory state/regional leave and 4 weeks of transition support. 1099 Contractors and Interns are ineligible (POL-012).",
        ]),
        ("Section 3. Medical Leave, FMLA, and Short-Term Disability", [
            "3.1 Serious Health Condition & FMLA Coordination: Eligible US employees needing extended time off (>5 consecutive business days) for a serious personal health condition or to care for a covered family member may take up to 12 weeks of job-protected leave under FMLA (where eligible) or Northstar Medical Leave.",
            "3.2 Short-Term Disability (STD) Income Replacement: For qualifying personal medical disabilities, Northstar's employer-paid STD plan coordinates with statutory benefits to provide 100% base salary replacement for weeks 1–6 and 70% base salary replacement for weeks 7–12.",
            "3.3 Benefits and PTO Accrual During Leave: During any 100% paid leave (Paid Parental Leave or paid STD period), medical/dental/vision coverage and PTO accrual continue uninterrupted. During strictly unpaid leave exceeding 30 calendar days, PTO accrual pauses prospectively until return to active status, while active health coverage continues provided employee premium shares are maintained.",
        ]),
        ("Section 4. Bereavement and Compassionate Leave", [
            "4.1 Immediate Family (10 Paid Business Days): FTEs receive up to 10 consecutive or intermittent paid business days following the loss of a spouse, domestic partner, child, parent, sibling, grandparent, grandchild, or corresponding in-law/step-relative, or pregnancy loss.",
            "4.2 Extended Family or Close Friend (5 Paid Business Days): FTEs receive up to 5 paid business days for extended family members or deeply close personal relationships. Bereavement leave does not deduct from accrued PTO balances.",
        ]),
        ("Section 5. Jury Duty, Voting, and Military Leave", [
            "5.1 Jury Duty & Subpoenaed Civic Service: FTEs summoned for mandatory jury service receive up to 15 business days of 100% paid civic leave per year upon providing the court summons to People Operations.",
            "5.2 Paid Voting Time: Employees are granted up to 3 paid hours on election days when polling hours conflict with scheduled shifts.",
            "5.3 Military Service: Northstar complies fully with USERRA and equivalent CA/UK reserve service protections, providing differential pay for up to 30 days of annual reserve training.",
        ]),
        ("Section 6. Return-to-Work Ramp and Privacy Protections", [
            "6.1 Gradual Return Ramp: Following Paid Parental Leave or Medical Leave exceeding 6 consecutive weeks, employees may opt into a 4-week 80% schedule ramp at 100% base pay in coordination with their manager and People Operations.",
            "6.2 Confidentiality of Medical Records: All physician certifications, FMLA forms, and accommodation documentation are stored in an encrypted People Operations vault separate from standard personnel and performance files.",
        ]),
    ]

    p5 = write_policy_pdf(
        "05_information_security_and_remote_access.pdf",
        "POL-005",
        "Information Security, Remote Access, and Travel Device Policy",
        [
            "Document ID: POL-005 | Category: security | Effective Date: January 1, 2026",
            "Owner: Northstar Information Security (infosec@northstarcloud.example)",
        ],
        pol_005_sections,
    )
    p9 = write_policy_pdf(
        "09_parental_medical_and_bereavement_leave.pdf",
        "POL-009",
        "Parental, Medical, Bereavement, and Civic Leave Policy",
        [
            "Document ID: POL-009 | Category: leave | Effective Date: January 1, 2026",
            "Owner: Northstar People Operations (people-ops@northstarcloud.example)",
        ],
        pol_009_sections,
    )
    print(f"Generated: {p5.name}, {p9.name}")


if __name__ == "__main__":
    main()
