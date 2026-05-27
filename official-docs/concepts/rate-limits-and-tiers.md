Rate Limits and Tiers
Understanding API rate limits, token costs, and access tiers

Documentation Index
Fetch the complete documentation index at: https://docs.kalshi.com/llms.txt

Use this file to discover all available pages before exploring further.

​
Token-based limits
Every authenticated request costs tokens. Your tier defines how many tokens you can spend per second. Most requests cost the default of 10 tokens; each operation’s API reference page lists its cost where it differs (order cancellations, single-order reads, quote create/cancel, and multivariate-collection lookup are currently cheaper than the default).
Your effective rate for any given endpoint is budget ÷ cost.
​
Reads and writes are billed separately
You have two independent token budgets:
Bucket	What it covers
Read	GET endpoints and anything not explicitly routed elsewhere.
Write	Order placement, amends, cancels, order groups, and the RFQ quote flow.
​
Batch endpoints don’t save tokens
A batch request costs the same as making each call individually — every item in the batch is billed separately:
Batch Create Orders: submitting 25 orders costs 25 × 10 = 250 tokens.
Batch Cancel Orders: cancelling 25 orders costs 25 × 2 = 50 tokens.
​
Tiers and budgets
Per-second token budgets in each bucket:
Tier	Read budget	Write budget
Basic	200	100
Advanced	300	300
Premier	1,000	1,000
Paragon	2,000	2,000
Prime	4,000	4,000
​
Tier qualification
Basic: complete account signup.
Advanced: complete the Advanced API application.
Premier, Paragon, Prime: qualification criteria will be published shortly.
Kalshi may, at its discretion, adjust your tier at any time — including downgrading you from higher tiers following prolonged inactivity. Members may request an upgrade by contacting support with a description of their use case.
​
When you hit the limit
A rate-limited request returns 429 Too Many Requests with the body:
{"error": "too many requests"}
429 responses don’t currently include Retry-After or X-RateLimit-* headers. Apply exponential backoff on 429 until your bucket refills.
​
Bursting above your per-second budget
Your Write bucket holds two seconds of your per-second budget — so idle or below-steady traffic builds up headroom you can spend in a single burst. Useful for event-driven clients reacting quickly to market moves or price prints. Each request drains the bucket by its token cost; the bucket refills continuously at your per-second budget up to its capacity.
Over-drawing returns 429 Too Many Requests. There’s no enforced cooldown — your next request is allowed as soon as the bucket has enough tokens to cover it.
Basic tier is the exception — its Write bucket holds one second of budget, with no accumulated headroom.