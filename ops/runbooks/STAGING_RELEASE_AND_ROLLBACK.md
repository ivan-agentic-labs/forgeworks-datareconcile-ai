# Staging release and rollback gate

Railway staging is pinned to a verified full commit SHA; pushes to main do not auto-deploy. This protects against untested changes but is not production acceptance.

## Promotion procedure
1. Identify a reviewed full SHA and verify all current application, contract, disposable PostgreSQL, tenant RLS and security CI workflows pass for that exact SHA.
2. Review migrations separately, test additive compatibility, retain rollback and backup. Never run review-only candidate SQL.
3. Promote the exact SHA to Railway staging, not a floating branch. Verify matching source SHA, SUCCESS deployment, readyz, live functional smoke, no 5xx/crash and tenant-isolation negative controls.
4. Record links to source/CI/deployment, reviewer decisions, migration proof, business acceptance, and rollback SHA. Unverified acceptance remains OPEN.

## Rollback
Previously verified staging SHA: `78455a7d009c8511b82806dec8e902ff95206b53`.
Current HTTP budget staging SHA: `075e79a9c4fc26f4af16b2fcab47aac09c49e8e9`.
Restore a prior verified commit if needed and recheck readiness. Never perform destructive schema rollback without a separate reviewed plan.

## OPEN blockers
- Two Supabase Auth users have server-owned grants, but no ACTIVE product memberships were verified. Do not auto-grant them.
- Supabase leaked-password protection disabled according to security advisor.
- Independent external readyz probe unavailable in this execution environment; Railway health != customer E2E.
- Live role-switching RLS proof through Supabase connector unavailable; disposable proofs are narrower.
- External storage retention/scanning, authenticated owner workflow, recovery drills, production SLO/load, finance controller signoff, and G3-G6 acceptance still required.
