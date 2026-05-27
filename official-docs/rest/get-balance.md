portfolio
Get Balance
Endpoint for getting the balance and portfolio value of a member. Both values are returned in cents.

GET

https://external-api.kalshi.com/trade-api/v2
/
portfolio
/
balance

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
subaccount
integer
Subaccount number (0 for primary, 1-32 for subaccounts). Defaults to 0.

Response

200

application/json
Balance retrieved successfully

​
balance
integer<int64>required
Member's available balance in cents. This represents the amount available for trading.

​
balance_dollars
stringrequired
Member's available balance as a fixed-point dollar string. This represents the amount available for trading.

Example:
"0.5600"

​
portfolio_value
integer<int64>required
Member's portfolio value in cents. This is the current value of all positions held.

​
updated_ts
integer<int64>required
Unix timestamp of the last update to the balance.

​
balance_breakdown
object[]
Balance broken down per exchange index.

Hide child attributes

​
balance_breakdown.exchange_index
integerrequired
Identifier for an exchange shard. Defaults to 0 if unspecified. Note: currently only 0 supported.

Example:
0

​
balance_breakdown.balance
stringrequired
US dollar amount as a fixed-point decimal string with up to 6 decimal places of precision. This is the maximum supported precision; valid quote intervals for a given market are constrained by that market's price level structure.

Example:
"0.5600"