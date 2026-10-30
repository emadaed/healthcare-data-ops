# Case Study: Building a Data Quality Control Engine for Healthcare Revenue Cycle Data

*Ahmad. Synthetic data throughout. This is a portfolio project, not client work.*

## The problem

In revenue cycle operations, money moves through claims, payments, denials and adjustments, and every one of those records can be wrong in a different way. A claim billed twice. A payment with no claim. A "Paid" claim with no cash behind it. Each error is small, but together they are the difference between reported revenue and real revenue.

The usual answer is people with spreadsheets reconciling by hand. I wanted to see how much of that can be turned into a repeatable, testable system, and how to prove it works rather than just claim it does.

I used a real job description (Senior Data Operations & Analyst, with Power BI, SQL, Python validation, Excel and Azure) as the specification. I did not apply for it. It gave me a realistic target instead of a made-up one.

## Where I'm coming from

My background is 15+ years in supply chain and operations in telecom and logistics, where I learned to trust numbers only after they reconcile. Before AI tools, that work lived in Excel and Access. I taught myself to code the systems that support that work. This project asks: can I apply that mindset to a domain I haven't worked in, and be honest about the gap?

In telecom supply chain operations, I led a multi-region, multi-warehouse inventory reconciliation for a Major Telecom (Middle East's largest managed services) project, ensuring absolute stock accuracy across dispersed hubs. Similarly, at Blue Light, I engineered end-to-end reconciliation for order lifecycles—matching all received and shipped transactions against cash receipts to precisely track outstanding customer receivables.

## Approach

**1. Start with an answer key.** My first generator injected errors at random and recorded nothing, which meant I could never measure whether the validator caught them. I rewrote it to log every injected problem in a ground-truth manifest. That one change made precision and recall possible.

**2. Separate two kinds of "bad."** A date written as `03/15/2025` instead of `2025-03-15` is a *formatting* issue: clean it and move on. A payment dated before the service is an *integrity* issue: flag it. Mixing the two is how validators drown people in false alarms. The cleaning layer logs what it fixed but never counts it as a failure.

**3. Make it fail first.** I built a harder dataset: near-duplicate billing, claims with two problems at once, about 1,400 formatting problems, and legitimate look-alikes that must not be flagged. My first validator scored **14.8% precision**: 925 false alarms. For example, 314 perfectly valid claims were called "missing service date" because of the date format. It also missed real overpayments because a charge was written as `$1,234.50`.

**4. Fix it, with tests.** I added the cleaning layer and a twelfth rule for near-duplicate billing. The result was 182 of 182 anomalies found with no false alarms. Each look-alike has a unit test so a future change can't quietly start flagging legitimate claims.

**5. Rebuild it where employers work.** I wrote the same rules in SQL, first on SQLite and then on Azure SQL in T-SQL, and compared results rule by rule against the Python engine. All 12 rules match on every record and on dollar totals. Two independent implementations agreeing caught problems that either alone would have hidden.

**6. Show it.** A Power BI model on a star schema, with measures for denial rate, days to pay and AR aging, a data quality scorecard page, and row-level security by payer.

## Decisions worth explaining

- **Flagged rows stay in the data.** They carry a `dq_flag`, so the report can show clean numbers or all numbers. Deleting bad rows would hide the problem.
- **Import mode in Power BI.** DirectQuery would wake the free-tier database on every click and use up its monthly compute allowance.
- **Rule severity drives tolerance.** A tiny failure rate on a financial rule is a breach. The same rate on a cosmetic rule is not.
- **Dollars at risk, not just counts.** "182 errors" is abstract. "$85,846 of exposure, led by orphan payments" is something a manager acts on.

## Results

| | Easy set | Hard set (first validator) | Hard set (final) |
|---|---|---|---|
| Anomalies injected | 150 | 182 | 182 |
| Precision | 100% | 14.8% | 100% |
| Recall | 100% | 88.5% | 100% |

34 automated tests pass. The Azure SQL warehouse builds in about a minute on the free tier.

## What I would not claim

- The 100% scores come from my own generator. They prove the pipeline works, not that it handles real data.
- I haven't worked with real US healthcare billing. The codes and prices are invented.
- The procedure code check uses a 14-code reference table, and the diagnosis check tests format only.
- The near-duplicate rule is a heuristic that would need human review in production.
- I did not use Microsoft Fabric, and the report is not published online. I mirrored the same layers in Azure SQL.

## What I would do next

1. Test against public, real-structure claims data (for example CMS public files) and report how the validator behaves.
2. Add an agent layer that reads the findings, proposes likely root causes, and drafts the reconciliation summary for a human to approve. This connects the project to my AI agent engineering direction.
3. Add dynamic row-level security with a user-to-payer mapping table.
4. Schedule the pipeline and track data quality scores over time.

## What I learned

The most valuable part wasn't the code. It was building something that could prove it was wrong. A validator that has never failed a test hasn't been tested. And most of the work in data quality is deciding what counts as an error and what is merely untidy.

---

*Code, tests, SQL, screenshots and the Power BI report: see the [README](README.md).*
