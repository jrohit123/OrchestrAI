# OrchestrAI Read Query Test Plan

Architecture: **LLM message router** → **read agent** (tools: `search_customers`, `run_query`) → live schema from DB.

Smoke test: `hi` → `top 3 customers by credit limit` → `dues Mehta` → `stock gold ring` → `which items need reordering`

---

## Advanced / reasoning queries (schema + SQL brain test)

These force joins, aggregation, sorting, comparison — not single-row lookups.

| # | Query | What LLM must figure out | Expected (from seed data) |
|---|-------|--------------------------|---------------------------|
| A1 | `top 3 customers by credit limit` | ORDER BY credit_limit DESC LIMIT 3 | Mehta ₹5L, Patel ₹4L, Sharma ₹3L |
| A2 | `which customers owe more than 1 lakh combined` | JOIN customers+invoices, SUM pending/overdue, HAVING | Sharma ~₹1.6L, Mehta ~₹1.07L |
| A3 | `rank all customers by total outstanding descending` | GROUP BY customer, SUM amounts | Sharma, Mehta, Agarwal, Kapoor/Patel ₹0 |
| A4 | `Mehta Jewellers ke saare invoices due date ke hisaab se sort karo` | JOIN + filter name + ORDER BY due_date | INV-001 (Jun 20), INV-004 (Jun 30) |
| A5 | `dues Mehta` → pick one OR `all` | Disambiguation if multiple Mehtas in DB | Per selection |
| A6 | `which inventory items need reordering` | qty <= reorder_level | Necklace (2≤10), Mangalsutra (15≤20), Diamond Bangle (12≤15) |
| A7 | `total stock value by location` | SUM(qty * unit_price) GROUP BY location | Agent computes from inventory |
| A8 | `customers who have used less than 50% of credit limit but have overdue invoices` | JOIN + credit_limit vs SUM outstanding | Logic-heavy — may be empty or Sharma |
| A9 | `compare Sharma and Mehta — who owes more and who has higher credit headroom` | Multi-customer aggregate + subtraction | Sharma owes more; Mehta has higher limit |
| A10 | `aging summary — group unpaid invoices by overdue buckets 30/60/90 days` | due_date vs today, CASE/WHERE status | Buckets by due dates in seed |
| A11 | `which customer has the most overdue invoices count not amount` | COUNT WHERE status=overdue GROUP BY | Sharma & Agarwal (1 each) |
| A12 | `list orders that are not delivered yet with customer city` | orders JOIN customers, status filter | ORD-1001 Mehta Mumbai, ORD-1002 Kapoor Pune |
| A13 | `average invoice amount per customer for unpaid only` | AVG+JOIN+status filter | Mehta avg ₹53.5k, Sharma ₹80k, Agarwal ₹71k |
| A14 | `show me customers in Mumbai with any pending dues` | city filter + join + sum>0 | Mehta Jewellers if only Mumbai with dues |
| A15 | `Patel ne pay kar diya kya — kitna total pay ho chuka` | paid status SUM | INV-003 ₹1,85,000 paid |
| A16 | `inventory items below reorder sorted by how critical lowest qty first` | WHERE qty<=reorder ORDER BY qty ASC | Necklace first (2 pcs) |
| A17 | `what percentage of total outstanding is from Sharma` | subquery totals | ~47% of total unpaid (~₹3.38L) |
| A18 | `give me a summary I can send to owner — top debtors and low stock in one answer` | Multi-query or complex SQL + narrative | Combined report |
| A19 | `22kt gold ring ka stock aur uska unit price multiply karke value batao` | Single row + calc | 41 × ₹45,000 = ₹18,45,000 |
| A20 | `konse customer ka credit limit exceed ho gaya outstanding se` | SUM(outstanding) > credit_limit | Likely none in seed data |

### Hinglish stress

| Query |
|-------|
| `sabse zyada limit kiske paas hai top 3 batao` |
| `jiska bhi stock reorder se kam hai sab list karo` |
| `Sharma aur Mehta ka compare karo kaun zyada baaki hai` |
| `pending aur overdue alag alag dikhao customer wise` |
