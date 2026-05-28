Get All Subaccount Balances
Gets balances for all subaccounts including the primary account.

GET

https://external-api.kalshi.com/trade-api/v2
/
portfolio
/
subaccounts
/
balances

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

Response

200

application/json
Balances retrieved successfully

​
subaccount_balances
object[]required
Hide child attributes

​
subaccount_balances.subaccount_number
integerrequired
Subaccount number (0 for primary, 1-32 for subaccounts).

​
subaccount_balances.balance
stringrequired
Balance in dollars.

Example:
"0.5600"

​
subaccount_balances.updated_ts
integer<int64>required
Unix timestamp of last balance update.