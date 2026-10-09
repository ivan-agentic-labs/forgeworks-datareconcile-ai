# DataReconcile AI — P0 Product Requirements & Scope

**Target buyer:** Finance operations/controller usaha dengan dua sumber transaksi CSV.

**Measurable user promise:** Merekonsiliasi dua daftar transaksi satu mata uang dengan aturan deterministik, mendeteksi exception, dan membuat laporan berjejak audit; AI hanya menjelaskan exception.

## P0 end-to-end workflow
Upload dua CSV → quarantine/parse strict → normalisasi minor units dan timezone → freeze batch hashes → deterministic exact 1:1 matching → unresolved exceptions → finance reviewer resolution → conservation validation → immutable report.

## Included in P0
- Dua file CSV bervolume terbatas dan satu mata uang per run
- Jumlah sebagai integer minor unit + policy pembulatan eksplisit
- Exact 1:1 matching dengan aturan versioned
- Exception approval dan signed report metadata

## Explicitly out of scope
- Transfer dana, akses perbankan langsung, settlement
- Fuzzy matching otomatis sebagai final decision
- Multi-currency FX conversion pada P0
- Aturan pajak/perlakuan akuntansi universal tanpa controller

## Roles & permission model
- `org_owner`: billing, org settings, members, quotas; does not automatically grant bypass to data policy.
- `org_admin`: invites within same tenant, configures allowed integrations, reviews impact.
- `editor`: creates runs/imports/draft analyses, cannot approve their own high-impact external write if separation-of-duty policy enables it.
- `reviewer`: approves signed revision/digest within policy and time window.
- `auditor`: read-only access to redacted audit + evidence.
- `service_worker`: machine identity with narrowly scoped effect grants, never unrestricted user impersonation; the BFF carries verified user access claims server-side.

## Product value and validation
Business hypothesis: targeted buyer experiences frequent repeatable failure that is expensive enough to justify adoption. Evidence needed: 3–5 structured buyer interviews, their current workaround, time/expense per incident, willingness to share consented/synthetic fixtures, and pilot pass criteria. These are **future prerequisites**, not interviews already done.

**North-star and guardrail metrics:** exact-match precision and recall on labeled ledger, unmatched exception rate, zero over-allocated transactions, report conservation discrepancy = 0, reviewer corrections per 1000 transactions.

## P0 completion criteria
1. One authorized end-to-end job reaches its intended output with reproducible fixture and trace.
2. Duplicate requests / partial external timeout / revocation / cross-tenant access fail safely.
3. Every material output cites a source/digest/rule version and has a reviewer action where needed.
4. Evidence of output correctness must come from deterministic assertion and human review of edge cases; AI alone does not sign off.
5. Security, privacy, budget, and recovery gate conditions defined in governance are respected.

## Critical G1 assumptions pending
- Finance controller must approve sign/refund/duplicate/conservation policy
- Retention and sensitive transaction treatment need legal review
- Dataset of labeled accounting cases needed before broad release

**Scope owner:** Founder/Product. **Security owner:** assigned reviewer. **Domain validator:** qualified buyer/SME. **Status:** PROVISIONAL, awaiting actual signed reviews.
