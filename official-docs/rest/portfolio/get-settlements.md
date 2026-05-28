Get Settlements
Endpoint for getting the member’s settlements historical track.

GET

https://external-api.kalshi.com/trade-api/v2
/
portfolio
/
settlements

Try it
Documentation Index
Fetch the complete documentation index at: https://docs.kalshi.com/llms.txt

Use this file to discover all available pages before exploring further.

Authorizations
​
KALSHI-ACCESS-KEY
stringheaderrequired
Your API key ID

​
KALSHI-ACCESS-SIGNATURE
stringheaderrequired
RSA-PSS signature of the request

​
KALSHI-ACCESS-TIMESTAMP
stringheaderrequired
Request timestamp in milliseconds

Query Parameters
​
limit
integer<int64>default:100
Number of results per page. Defaults to 100.

Required range: 1 <= x <= 1000
​
cursor
string
Pagination cursor. Use the cursor value returned from the previous response to get the next page of results. Leave empty for the first page.

​
ticker
string
Filter by market ticker

​
event_ticker
string
Event ticker to filter by. Only a single event ticker is supported.

​
min_ts
integer<int64>
Filter items after this Unix timestamp

​
max_ts
integer<int64>
Filter items before this Unix timestamp

​
subaccount
integer
Subaccount number (0 for primary, 1-32 for subaccounts). If omitted, defaults to all subaccounts.

Response

200

application/json
Settlements retrieved successfully

​
settlements
object[]required
Hide child attributes

​
settlements.ticker
stringrequired
The ticker symbol of the market that was settled.

​
settlements.event_ticker
stringrequired
The event ticker symbol of the market that was settled.

​
settlements.market_result
enum<string>required
The outcome of the market settlement. 'yes' = market resolved to YES, 'no' = market resolved to NO, 'scalar' = scalar market settled at a specific value, 'void' = market was voided/cancelled and all positions returned at original cost.

Available options: yes, no, scalar, void 
​
settlements.yes_count_fp
stringrequired
String representation of the number of YES contracts owned at the time of settlement.

Example:
"10.00"

​
settlements.yes_total_cost_dollars
stringrequired
Total cost basis of all YES contracts in fixed-point dollars.

Example:
"0.5600"

​
settlements.no_count_fp
stringrequired
String representation of the number of NO contracts owned at the time of settlement.

Example:
"10.00"

​
settlements.no_total_cost_dollars
stringrequired
Total cost basis of all NO contracts in fixed-point dollars.

Example:
"0.5600"

​
settlements.revenue
integerrequired
Total revenue earned from this settlement in cents (winning contracts pay out 100 cents each).

​
settlements.settled_time
string<date-time>required
Timestamp when the market was settled and payouts were processed.

​
settlements.fee_cost
stringrequired
Total fees paid in fixed point dollars.

Example:
"0.3400"

​
settlements.value
integer | null
Payout of a single yes contract in cents.

​
cursor
string