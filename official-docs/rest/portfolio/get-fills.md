2Get Fills
Endpoint for getting all fills for the member. A fill is when a trade you have is matched. Fills that occurred before the historical cutoff are only available via GET /historical/fills. See Historical Data for details.

GET

https://external-api.kalshi.com/trade-api/v2
/
portfolio
/
fills

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
ticker
string
Filter by market ticker

​
order_id
string
Filter by order ID

​
min_ts
integer<int64>
Filter items after this Unix timestamp

​
max_ts
integer<int64>
Filter items before this Unix timestamp

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
subaccount
integer
Subaccount number (0 for primary, 1-32 for subaccounts). If omitted, defaults to all subaccounts.

Response

200

application/json
Fills retrieved successfully

​
fills
object[]required
Hide child attributes

​
fills.fill_id
stringrequired
Unique identifier for this fill

​
fills.trade_id
stringrequired
Unique identifier for this fill (legacy field name, same as fill_id)

​
fills.order_id
stringrequired
Unique identifier for the order that resulted in this fill

​
fills.ticker
stringrequired
Unique identifier for the market

​
fills.market_ticker
stringrequired
Unique identifier for the market (legacy field name, same as ticker)

​
fills.side
enum<string>requireddeprecated
Deprecated. Use outcome_side (or book_side) instead. See Order direction. This field will not be removed before May 14, 2026.

Available options: yes, no 
​
fills.action
enum<string>requireddeprecated
Deprecated. Use outcome_side (or book_side) instead. See Order direction. This field will not be removed before May 14, 2026.

Available options: buy, sell 
​
fills.outcome_side
enum<string>required
The outcome side this fill positioned the user for. buy-yes and sell-no produce 'yes'; buy-no and sell-yes produce 'no'.

outcome_side describes directional exposure only; it does not change the fill's price. A fill at price p with outcome_side=no is matched against an order at the same price p with outcome_side=yes — both parties trade at the same price, just on opposite directions.

outcome_side and book_side will become the canonical way to determine fill direction. The legacy action and side fields will be deprecated in a future release — please migrate to these new fields.

Available options: yes, no 
​
fills.book_side
enum<string>required
Same directional bit as outcome_side in book vocabulary. 'bid' is equivalent to outcome_side 'yes'; 'ask' is equivalent to outcome_side 'no'.

outcome_side and book_side will become the canonical way to determine fill direction. The legacy action and side fields will be deprecated in a future release — please migrate to these new fields.

Available options: bid, ask 
​
fills.count_fp
stringrequired
String representation of the number of contracts bought or sold in this fill

Example:
"10.00"

​
fills.yes_price_dollars
stringrequired
Fill price for the yes side in fixed-point dollars

Example:
"0.5600"

​
fills.no_price_dollars
stringrequired
Fill price for the no side in fixed-point dollars

Example:
"0.5600"

​
fills.is_taker
booleanrequired
If true, this fill was a taker (removed liquidity from the order book)

​
fills.fee_cost
stringrequired
Fee cost in fixed-point dollars

Example:
"0.5600"

​
fills.created_time
string<date-time>
Timestamp when this fill was executed

​
fills.subaccount_number
integer | null
Subaccount number (0 for primary, 1-32 for subaccounts). Present for direct users.

​
fills.ts
integer<int64>
Unix timestamp when this fill was executed (legacy field name)

​
cursor
stringrequired