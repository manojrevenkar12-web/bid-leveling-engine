# ADR 0002: Postgres with SQL migrations instead of an ORM (build vs buy)

Status: accepted

## Context
The platform needs a small relational model (tenders, versions, positions, bids, lines, findings,
decisions) and transactional run replacement. Prisma was the first choice to match the target
stack, but its engine binaries are downloaded at install time, which failed in this build
environment (blocked host) and would need a mirror in CI and air-gapped customer installs.

## Decision
`pg` with plain SQL migrations (`platform/sql/*.sql`, applied in order, recorded in
`schema_migration`) and a small transaction helper.

## Consequences
+ No binary download, nothing generated, one dependency; queries are visible in review.
+ Storing a run is one transaction; a failing run leaves the previous one in place (tested).
− No generated types for rows; route handlers type their results by hand.
− Moving to Prisma later is cheap: the schema is in one SQL file.
