Cancel Order
Endpoint for canceling orders. The value for the orderId should match the id field of the order you want to decrease. Commonly, DELETE-type endpoints return 204 status with no body content on success. But we can’t completely delete the order, as it may be partially filled already. Instead, the DeleteOrder endpoint reduce the order completely, essentially zeroing the remaining resting contracts on it. The zeroed order is returned on the response payload as a form of validation for the client.

DELETE

https://external-api.kalshi.com/trade-api/v2
/
portfolio
/
orders
/
{order_id}

Try it
Documentation Index
Fetch the complete documentation index at: https://docs.kalshi.com/llms.txt

Use this file to discover all available pages before exploring further.

Rate limit: 2 tokens per request. Other endpoints use the default cost of 10 tokens per request unless noted on their own page. See Rate Limits and Tiers.
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

Path Parameters
​
order_id
stringrequired
Order ID

Query Parameters
​
subaccount
integer
Subaccount number (0 for primary, 1-32 for subaccounts). Defaults to 0.

​
exchange_index
integer
Identifier for an exchange shard. Defaults to 0 if unspecified. Note: currently only 0 supported.

Example:
0

Response

200

application/json
Order cancelled successfully

​
order
objectrequired
Hide child attributes

​
order.order_id
stringrequired
​
order.user_id
stringrequired
Unique identifier for users

​
order.client_order_id
stringrequired
​
order.ticker
stringrequired
​
order.side
enum<string>requireddeprecated
Deprecated. Use outcome_side (or book_side) instead. See Order direction. This field will not be removed before May 14, 2026.

Available options: yes, no 
​
order.action
enum<string>requireddeprecated
Deprecated. Use outcome_side (or book_side) instead. See Order direction. This field will not be removed before May 14, 2026.

Available options: buy, sell 
​
order.outcome_side
enum<string>required
The outcome side this order is positioned for. buy-yes and sell-no produce 'yes'; buy-no and sell-yes produce 'no'.

outcome_side describes directional exposure only; it does not change the order's price. An order at price p with outcome_side=no is matched by an order at the same price p with outcome_side=yes — both parties trade at the same price, just on opposite directions.

outcome_side and book_side will become the canonical way to determine order direction. The legacy action, side, and is_yes fields will be deprecated in a future release — please migrate to these new fields.

Available options: yes, no 
​
order.book_side
enum<string>required
Same directional bit as outcome_side in book vocabulary. 'bid' is equivalent to outcome_side 'yes'; 'ask' is equivalent to outcome_side 'no'.

outcome_side and book_side will become the canonical way to determine order direction. The legacy action, side, and is_yes fields will be deprecated in a future release — please migrate to these new fields.

Available options: bid, ask 
​
order.type
enum<string>required
Available options: limit, market 
​
order.status
enum<string>required
The status of an order

Available options: resting, canceled, executed 
​
order.yes_price_dollars
stringrequired
The yes price for this order in fixed-point dollars

Example:
"0.5600"

​
order.no_price_dollars
stringrequired
The no price for this order in fixed-point dollars

Example:
"0.5600"

​
order.fill_count_fp
stringrequired
String representation of the number of contracts that have been filled

Example:
"10.00"

​
order.remaining_count_fp
stringrequired
String representation of the remaining contracts for this order

Example:
"10.00"

​
order.initial_count_fp
stringrequired
String representation of the initial size of the order (contract units)

Example:
"10.00"

​
order.taker_fill_cost_dollars
stringrequired
The cost of filled taker orders in dollars

Example:
"0.5600"

​
order.maker_fill_cost_dollars
stringrequired
The cost of filled maker orders in dollars

Example:
"0.5600"

​
order.taker_fees_dollars
stringrequired
Fees paid on filled taker contracts, in dollars

Example:
"0.5600"

​
order.maker_fees_dollars
stringrequired
Fees paid on filled maker contracts, in dollars

Example:
"0.5600"

​
order.expiration_time
string<date-time> | null
​
order.created_time
string<date-time> | null
​
order.last_update_time
string<date-time> | null
The last update to an order (modify, cancel, fill)

​
order.self_trade_prevention_type
enum<string> | null
The self-trade prevention type for orders. taker_at_cross cancels the taker order when it would trade against another order from the same user; execution stops and any partial fills already matched are executed. maker cancels the resting maker order and continues matching.

Available options: taker_at_cross, maker 
​
order.order_group_id
string | null
The order group this order is part of

​
order.cancel_order_on_pause
boolean
If this flag is set to true, the order will be canceled if the order is open and trading on the exchange is paused for any reason.

​
order.subaccount_number
integer | null
Subaccount number (0 for primary, 1-32 for subaccounts).

​
order.exchange_index
integer
Identifier for an exchange shard. Defaults to 0 if unspecified. Note: currently only 0 supported.

Example:
0

​
reduced_by_fp
stringrequired
String representation of the number of contracts that were successfully canceled from this order

Example:
"10.00"