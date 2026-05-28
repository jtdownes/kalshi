Create Order (V2)
Endpoint for submitting event-market orders using the V2 request/response shape (single-book bid/ask side and fixed-point dollar prices). The legacy /portfolio/orders endpoint will be deprecated no earlier than May 6, 2026 — clients should migrate to this path.

POST

https://external-api.kalshi.com/trade-api/v2
/
portfolio
/
events
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

Body
application/json
​
ticker
stringrequired
​
client_order_id
stringrequired
​
side
enum<string>required
Side of the book for an order or trade. For event markets, this refers to the YES leg only: bid means buy YES, ask means sell YES. (Selling YES is economically equivalent to buying NO at 1 - price, but this endpoint quotes everything from the YES side.)

Available options: bid, ask 
​
count
stringrequired
String representation of the order quantity in contracts.

Example:
"10.00"

​
price
stringrequired
Price for the order in fixed-point dollars.

Example:
"0.5600"

​
time_in_force
enum<string>required
Specifies how long the order remains active. Use good_till_canceled
with expiration_time for an order that should rest until a specific
expiration time; without expiration_time, good_till_canceled is a
true good-till-canceled order. GTT is not a valid API value.

Available options: fill_or_kill, good_till_canceled, immediate_or_cancel 
​
self_trade_prevention_type
enum<string>required
The self-trade prevention type for orders. taker_at_cross cancels the taker order when it would trade against another order from the same user; execution stops and any partial fills already matched are executed. maker cancels the resting maker order and continues matching.

Available options: taker_at_cross, maker 
​
expiration_time
integer<int64>
Optional Unix timestamp in seconds for when the order expires. To place
an expiring order, set time_in_force to good_till_canceled and
provide this expiration_time. GTT is an internal execution type and
is not a valid API value for time_in_force. The
immediate_or_cancel time-in-force value cannot be combined with
expiration_time.

​
post_only
boolean
​
cancel_order_on_pause
boolean
If this flag is set to true, the order will be canceled if the order is open and trading on the exchange is paused for any reason.

​
reduce_only
boolean
Specifies whether the order place count should be capped by the member's current position.

​
subaccount
integerdefault:0
The subaccount number to use for this order. 0 is the primary subaccount.

Required range: x >= 0
​
order_group_id
string
The order group this order is part of

​
exchange_index
integerdefault:0
Identifier for an exchange shard. Defaults to 0 if unspecified. Note: currently only 0 supported.

Example:
0

Response

201

application/json
Order created successfully

​
order_id
stringrequired
​
fill_count
stringrequired
Number of contracts filled immediately upon placement.

Example:
"10.00"

​
remaining_count
stringrequired
Number of contracts remaining after placement. For IOC orders, this reflects the final state after unfilled contracts are canceled.

Example:
"10.00"

​
ts_ms
integer<int64>required
Matching engine timestamp at which the order was processed, as Unix epoch milliseconds.

​
client_order_id
string
​
average_fill_price
string
Volume-weighted average fill price. Only present when fill_count > 0.

Example:
"0.5600"

​
average_fee_paid
string
Volume-weighted average fee paid per contract for fills resulting from this request. Only present when fill_count > 0.

Example:
"0.5600"