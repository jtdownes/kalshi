Market Ticker
Market price, volume, and open interest updates.

Requirements:

No additional channel-level authentication beyond the authenticated WebSocket connection
Market specification optional (omit to receive all markets)
Supports market_ticker/market_tickers and market_id/market_ids
Updates sent whenever any ticker field changes
Use case: Displaying current market prices and statistics

WSS
ticker
Documentation Index
Fetch the complete documentation index at: https://docs.kalshi.com/llms.txt

Use this file to discover all available pages before exploring further.

Messages

Ticker Update

Security Schemes
apiKey
type:
apiKey
API key authentication required for WebSocket connections.
The API key should be provided during the WebSocket handshake.


Receive
Ticker Update
type:
object

hide 3 properties
Market price ticker information

type
type:
string
required
ticker

sid
type:
integer
required
Server-generated subscription identifier (sid) used to identify the channel

msg
type:
object
required

hide 15 properties
market_ticker
type:
string
required
Unique market identifier

Examples: FED-23DEC-T3.00, HIGHNY-22DEC23-B53.5
market_id
type:
string
required
Unique market UUID

price_dollars
type:
string
required
Last traded price in dollars

yes_bid_dollars
type:
string
required
Best bid price for yes side in dollars

yes_ask_dollars
type:
string
required
Best ask price for yes side in dollars

volume_fp
type:
string
required
Fixed-point total contracts traded (2 decimals)

open_interest_fp
type:
string
required
Fixed-point open interest (2 decimals)

dollar_volume
type:
integer
required
Number of dollars traded in the market so far

dollar_open_interest
type:
integer
required
Number of dollars positioned in the market currently

yes_bid_size_fp
type:
string
required
Fixed-point contracts at best bid (2 decimals)

yes_ask_size_fp
type:
string
required
Fixed-point contracts at best ask (2 decimals)

last_trade_size_fp
type:
string
required
Fixed-point contracts in last trade (2 decimals)

ts
type:
integer
required
deprecated
Deprecated - Unix timestamp for when the update happened (in seconds). Use ts_ms instead.

ts_ms
type:
integer
required
Unix timestamp for when the update happened (in milliseconds)

time
type:
string
required
deprecated
Deprecated - Timestamp for when the update happened (RFC3339). Use ts_ms instead.