User Fills
Your order fill notifications. Requires authentication.

Requirements:

Authentication required
Market specification optional via market_ticker/market_tickers (omit to receive all your fills)
Supports update_subscription with add_markets / delete_markets
Updates sent immediately when your orders are filled
Use case: Tracking your trading activity

WSS
fill
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
Fill Update
type:
object

hide 3 properties
Private fill information for authenticated user

type
type:
string
required
fill

sid
type:
integer
required
Server-generated subscription identifier (sid) used to identify the channel

msg
type:
object
required

hide 17 properties
trade_id
type:
string
required
Unique identifier for fills. This is what you use to differentiate fills

order_id
type:
string
required
Unique identifier for orders. This is what you use to differentiate fills for different orders

market_ticker
type:
string
required
Unique market identifier

Examples: FED-23DEC-T3.00, HIGHNY-22DEC23-B53.5
is_taker
type:
boolean
required
If you were a taker on this fill

side
type:
enum
required
Market side

Available options: yes, no
yes_price_dollars
type:
string
required
Price for the yes side of the fill in dollars

count_fp
type:
string
required
Fixed-point contracts filled (2 decimals)

fee_cost
type:
string
required
Exchange fee paid for this fill in fixed-point dollars

action
type:
enum
required
Order action type

Available options: buy, sell
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

client_order_id
type:
string
Optional client-provided order ID

post_position_fp
type:
string
required
Fixed-point position after the fill (2 decimals)

purchased_side
type:
enum
required
Market side

Available options: yes, no
outcome_side
type:
enum
required
Market side

Available options: yes, no
book_side
type:
enum
required
Side of the book for an order or trade. 'bid' is equivalent to outcome_side 'yes'; 'ask' is equivalent to outcome_side 'no'.

Available options: bid, ask
subaccount
type:
integer
Optional subaccount number for the fill