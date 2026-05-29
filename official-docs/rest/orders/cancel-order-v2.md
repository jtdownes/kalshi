Cancel Order (V2)
Endpoint for cancelling event-market orders using the V2 response shape. Returns {order_id, client_order_id, reduced_by} rather than a full order object.

DELETE

https://external-api.kalshi.com/trade-api/v2
/
portfolio
/
events
/
orders
/
{order_id}

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
order_id
stringrequired
​
reduced_by
stringrequired
Number of contracts that were canceled (i.e. the remaining count at time of cancellation).

Example:
"10.00"

​
ts_ms
integer<int64>required
Matching engine timestamp at which the cancellation was processed, as Unix epoch milliseconds.

​
client_order_id
string