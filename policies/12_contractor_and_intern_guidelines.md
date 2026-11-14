# POL-012: Contractor and Fixed-Term Intern Guidelines

- **Document ID:** POL-012
- **Policy Title:** Contractor and Fixed-Term Intern Guidelines
- **Category:** `onboarding`
- **Effective Date:** January 1, 2026
- **Owner:** Northstar People Operations & Procurement (`people-ops@northstarcloud.example`)

## 1. Purpose and Worker Classification Distinction

Northstar Cloud Labs, Inc. engages 1099 Independent Contractors, external consultants, and Fixed-Term Interns (typically 10–16 week university or seasonal cohorts) alongside regular W-2 / full-time employees (FTEs). Maintaining clear legal and operational classification boundaries protects both Northstar and external workers from statutory misclassification risks while setting transparent expectations around benefits, time off, equipment, and expenses.

Engagement terms for contractors are governed primarily by their executed Master Services Agreement (MSA) and Statement of Work (SOW). Where an SOW is silent on workplace operations, this policy governs.

## 2. Benefits and Paid Leave Exclusions

Unless explicitly mandated by applicable local statutory law or explicitly negotiated in an approved SOW:

- **Paid Time Off & Holidays:** Contractors and fixed-term interns do **not** accrue paid vacation PTO under **POL-001** and are **not** paid for unworked statutory company holidays, floating holidays, or the annual Winter Recharge shutdown under **POL-002**. Contractors invoice solely for actual authorized hours worked or accepted milestone deliverables.
- **Health Insurance & Retirement Match:** Contractors and fixed-term interns are **ineligible** for company-sponsored medical, dental, vision, HSA contributions, 401(k) / RRSP / UK pension employer matching, short-term disability, and paid parental leave (**POL-006**, **POL-009**).
- **Employee Stipends (Home Office, Wellness, L&D):** Contractors and fixed-term interns are **ineligible** for the one-time **$500 Home Office Ergonomic Stipend** (**POL-004 Section 5**), the **$100/month Wellness Stipend**, and the **$2,500/year Learning & Development (L&D) Budget** (**POL-006**).

## 3. Expenses, Travel Reimbursement, and Equipment

### 3.1 Pre-Approval Requirement for Contractor Travel
Contractors may not charge unapproved travel, meals, software licenses, or equipment to Northstar. Any reimbursable business travel explicitly required by an SOW must be pre-approved in writing by the sponsoring Department Director or VP prior to booking and must strictly comply with Northstar's standard reimbursement caps (**$75/day** domestic meals, **$100/day** international meals, **$275/night** standard hotel cap, Economy airfare under 6 hours per **POL-004**).

### 3.2 Computing Hardware and BYOD Boundaries
- **1099 Contractors:** Provide their own personal workstation and ergonomic office setup (`BYOD`) unless InfoSec issues a time-bounded company loaner specifically for elevated repository work. Contractors cannot expense personal laptops or ergonomic chairs.
- **Fixed-Term Interns:** Receive a refurbished corporate loaner laptop from IT Operations (**POL-008 Section 2**) for the duration of their cohort, which must be returned within 5 business days after the final day of the internship.

## 4. Security, Access Controls (`Contractor-Limited`), and Conduct

Contractors are assigned the `Contractor-Limited` security profile (**POL-005 Section 4**):
- Access is strictly scoped on a least-privilege basis to designated repositories, staging environments, and project documentation required by the SOW.
- Contractors are prohibited from accessing unmasked production customer databases (`Prod-Admin` or `Customer-PII`) unless granted a documented, time-bounded break-glass exception by InfoSec (`infosec@northstarcloud.example`) using a Northstar-managed clean device.
- Hardware FIDO2 MFA and corporate WireGuard VPN rules apply whenever accessing Northstar internal services.
- All contractors and interns are bound by Northstar's Code of Conduct, Confidentiality, and Anti-Harassment Policy (**POL-010**) and have full access to confidential reporting via `ethics@northstarcloud.example`.
