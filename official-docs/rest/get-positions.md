portfolio
Get Positions
Restricts the positions to those with any of following fields with non-zero values, as a comma separated list. The following values are accepted: position, total_traded

GET

https://external-api.kalshi.com/trade-api/v2
/
portfolio
/
positions

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
cursor
string
The Cursor represents a pointer to the next page of records in the pagination. Use the value returned from the previous response to get the next page.

​
limit
integer<int32>default:100
Parameter to specify the number of results per page. Defaults to 100.

Required range: 1 <= x <= 1000
​
count_filter
string
Restricts the positions to those with any of following fields with non-zero values, as a comma separated list. The following values are accepted - position, total_traded

​
ticker
string
Filter by market ticker

​
event_ticker
string
Event ticker to filter by. Only a single event ticker is supported.

​
subaccount
integer
Subaccount number (0 for primary, 1-32 for subaccounts). Defaults to 0.

Response

200

application/json
Positions retrieved successfully

​
market_positions
object[]required
List of market positions

Hide child attributes

​
market_positions.ticker
stringrequired
Unique identifier for the market

​
market_positions.total_traded_dollars
stringrequired
Total spent on this market in dollars

Example:
"0.5600"

​
market_positions.position_fp
stringrequired
String representation of the number of contracts bought in this market. Negative means NO contracts and positive means YES contracts

Example:
"10.00"

​
market_positions.market_exposure_dollars
stringrequired
Cost of the aggregate market position in dollars

Example:
"0.5600"

​
market_positions.realized_pnl_dollars
stringrequired
Locked in profit and loss, in dollars

Example:
"0.5600"

​
market_positions.resting_orders_count
integer<int32>requireddeprecated
[DEPRECATED] Aggregate size of resting orders in contract units

​
market_positions.fees_paid_dollars
stringrequired
Fees paid on fill orders, in dollars

Example:
"0.5600"

​
market_positions.last_updated_ts
string<date-time>required
Last time the position is updated

​
event_positions
object[]required
List of event positions

Hide child attributes

​
event_positions.event_ticker
stringrequired
Unique identifier for events

​
event_positions.total_cost_dollars
stringrequired
Total spent on this event in dollars

Example:
"0.5600"

​
event_positions.total_cost_shares_fp
stringrequired
String representation of the total number of shares traded on this event (including both YES and NO contracts)

Example:
"10.00"

​
event_positions.event_exposure_dollars
stringrequired
Cost of the aggregate event position in dollars

Example:
"0.5600"

​
event_positions.realized_pnl_dollars
stringrequired
Locked in profit and loss, in dollars

Example:
"0.5600"

​
event_positions.fees_paid_dollars
stringrequired
Fees paid on fill orders, in dollars

Example:
"0.5600"

​
cursor
string
The Cursor represents a pointer to the next page of records in the pagination. Use the value returned here in the cursor query parameter for this end-point to get the next page containing limit records. An empty value of this field indicates there is no next page.