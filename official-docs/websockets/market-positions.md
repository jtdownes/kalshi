Market Positions
Real-time updates of your positions in markets. Requires authentication.

Requirements:

Authentication required
Market specification optional (omit to receive all positions)
Filters are by market_ticker/market_tickers only; market_id/market_ids are not supported
Updates sent when your position changes due to trades, settlements, etc.
Monetary Values: All monetary values are returned as fixed-point dollar strings (_dollars suffix).

Use case: Portfolio tracking, position monitoring, P&L calculations

WSS
market_positions
Documentation Index
Fetch the complete documentation index at: https://docs.kalshi.com/llms.txt

Use this file to discover all available pages before exploring further.


Security Schemes
apiKey
type:
apiKey
API key authentication required for WebSocket connections.
The API key should be provided during the WebSocket handshake.


Receive
Market Position Update
type:
object

hide 3 properties
Real-time position updates for authenticated user

type
type:
string
required
market_position

sid
type:
integer
required
Server-generated subscription identifier (sid) used to identify the channel

msg
type:
object
required

hide 9 properties
user_id
type:
string
required
User ID for the position

market_ticker
type:
string
required
Unique market identifier

Examples: FED-23DEC-T3.00, HIGHNY-22DEC23-B53.5
position_fp
type:
string
required
Fixed-point net position (2 decimals)

position_cost_dollars
type:
string
required
Current cost basis of the position as a fixed-point dollar string

realized_pnl_dollars
type:
string
required
Realized profit/loss as a fixed-point dollar string

fees_paid_dollars
type:
string
required
Total fees paid as a fixed-point dollar string

position_fee_cost_dollars
type:
string
required
Total position fee cost as a fixed-point dollar string

volume_fp
type:
string
required
Fixed-point total volume traded (2 decimals)

subaccount
type:
integer
Optional subaccount number for the position