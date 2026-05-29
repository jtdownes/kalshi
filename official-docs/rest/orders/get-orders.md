Get Orders
Restricts the response to orders that have a certain status: resting, canceled, or executed. Orders that have been canceled or fully executed before the historical cutoff are only available via GET /historical/orders. Resting orders will always be available through this endpoint. See Historical Data for details.

GET

https://external-api.kalshi.com/trade-api/v2
/
portfolio
/
orders

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
event_ticker
string
Event tickers to filter by, as a comma-separated list (maximum 10).

​
min_ts
integer<int64>
Filter items after this Unix timestamp

​
max_ts
integer<int64>
Filter items before this Unix timestamp

​
status
string
Filter by status. Possible values depend on the endpoint.

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
Orders retrieved successfully

​
orders
object[]required
Hide child attributes

​
orders.order_id
stringrequired
​
orders.user_id
stringrequired
Unique identifier for users

​
orders.client_order_id
stringrequired
​
orders.ticker
stringrequired
​
orders.side
enum<string>requireddeprecated
Deprecated. Use outcome_side (or book_side) instead. See Order direction. This field will not be removed before May 14, 2026.

Available options: yes, no 
​
orders.action
enum<string>requireddeprecated
Deprecated. Use outcome_side (or book_side) instead. See Order direction. This field will not be removed before May 14, 2026.

Available options: buy, sell 
​
orders.outcome_side
enum<string>required
The outcome side this order is positioned for. buy-yes and sell-no produce 'yes'; buy-no and sell-yes produce 'no'.

outcome_side describes directional exposure only; it does not change the order's price. An order at price p with outcome_side=no is matched by an order at the same price p with outcome_side=yes — both parties trade at the same price, just on opposite directions.

outcome_side and book_side will become the canonical way to determine order direction. The legacy action, side, and is_yes fields will be deprecated in a future release — please migrate to these new fields.

Available options: yes, no 
​
orders.book_side
enum<string>required
Same directional bit as outcome_side in book vocabulary. 'bid' is equivalent to outcome_side 'yes'; 'ask' is equivalent to outcome_side 'no'.

outcome_side and book_side will become the canonical way to determine order direction. The legacy action, side, and is_yes fields will be deprecated in a future release — please migrate to these new fields.

Available options: bid, ask 
​
orders.type
enum<string>required
Available options: limit, market 
​
orders.status
enum<string>required
The status of an order

Available options: resting, canceled, executed 
​
orders.yes_price_dollars
stringrequired
The yes price for this order in fixed-point dollars

Example:
"0.5600"

​
orders.no_price_dollars
stringrequired
The no price for this order in fixed-point dollars

Example:
"0.5600"

​
orders.fill_count_fp
stringrequired
String representation of the number of contracts that have been filled

Example:
"10.00"

​
orders.remaining_count_fp
stringrequired
String representation of the remaining contracts for this order

Example:
"10.00"

​
orders.initial_count_fp
stringrequired
String representation of the initial size of the order (contract units)

Example:
"10.00"

​
orders.taker_fill_cost_dollars
stringrequired
The cost of filled taker orders in dollars

Example:
"0.5600"

​
orders.maker_fill_cost_dollars
stringrequired
The cost of filled maker orders in dollars

Example:
"0.5600"

​
orders.taker_fees_dollars
stringrequired
Fees paid on filled taker contracts, in dollars

Example:
"0.5600"

​
orders.maker_fees_dollars
stringrequired
Fees paid on filled maker contracts, in dollars

Example:
"0.5600"

​
orders.expiration_time
string<date-time> | null
​
orders.created_time
string<date-time> | null
​
orders.last_update_time
string<date-time> | null
The last update to an order (modify, cancel, fill)

​
orders.self_trade_prevention_type
enum<string> | null
The self-trade prevention type for orders. taker_at_cross cancels the taker order when it would trade against another order from the same user; execution stops and any partial fills already matched are executed. maker cancels the resting maker order and continues matching.

Available options: taker_at_cross, maker 
​
orders.order_group_id
string | null
The order group this order is part of

​
orders.cancel_order_on_pause
boolean
If this flag is set to true, the order will be canceled if the order is open and trading on the exchange is paused for any reason.

​
orders.subaccount_number
integer | null
Subaccount number (0 for primary, 1-32 for subaccounts).

​
orders.exchange_index
integer
Identifier for an exchange shard. Defaults to 0 if unspecified. Note: currently only 0 supported.

Example:
0