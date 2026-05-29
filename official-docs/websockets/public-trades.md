Public Trades
Public trade notifications when trades occur.

Requirements:

No additional channel-level authentication beyond the authenticated WebSocket connection
Market specification optional (omit to receive all trades)
Updates sent immediately after trade execution
Use case: Trade feed, volume analysis

WSS
trade
Documentation Index
Fetch the complete documentation index at: https://docs.kalshi.com/llms.txt

Use this file to discover all available pages before exploring further.

Messages

Trade Update

Security Schemes
apiKey
type:
apiKey
API key authentication required for WebSocket connections.
The API key should be provided during the WebSocket handshake.


Receive
Trade Update
type:
object

hide 3 properties
Public trade information

type
type:
string
required
trade

sid
type:
integer
required
Server-generated subscription identifier (sid) used to identify the channel

msg
type:
object
required

hide 10 properties
trade_id
type:
string
required
Unique identifier for the trade

market_ticker
type:
string
required
Unique market identifier

Examples: FED-23DEC-T3.00, HIGHNY-22DEC23-B53.5
yes_price_dollars
type:
string
required
Yes side price in dollars

no_price_dollars
type:
string
required
No side price in dollars

count_fp
type:
string
required
Fixed-point contracts traded (2 decimals)

taker_side
type:
enum
required
Market side

Available options: yes, no
taker_outcome_side
type:
enum
required
Market side

Available options: yes, no
taker_book_side
type:
enum
required
Side of the book for an order or trade. 'bid' is equivalent to outcome_side 'yes'; 'ask' is equivalent to outcome_side 'no'.

Available options: bid, ask
ts
type:
integer
required
deprecated
Deprecated - Unix timestamp in seconds. Use ts_ms instead.

ts_ms
type:
integer
required
Unix timestamp in milliseconds