User Orders
Real-time order created and updated notifications. Requires authentication.

Requirements:

Authentication required
Market specification optional via market_tickers (omit to receive all orders)
Supports update_subscription with add_markets / delete_markets actions
Updates sent when your orders are created, filled, canceled, or otherwise updated
Use case: Tracking your resting orders, fills, and cancellations in real time

WSS
user_orders
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
User Order Update
type:
object

hide 3 properties
Real-time order updates for authenticated user

type
type:
string
required
user_order

sid
type:
integer
required
Server-generated subscription identifier (sid) used to identify the channel

msg
type:
object
required

hide 26 properties
order_id
type:
string
required
Unique order identifier

user_id
type:
string
required
User identifier

ticker
type:
string
required
Unique market identifier

Examples: FED-23DEC-T3.00, HIGHNY-22DEC23-B53.5
status
type:
enum
required
Current order status

Available options: resting, canceled, executed
side
type:
enum
required
Market side

Available options: yes, no
is_yes
type:
boolean
required
deprecated
Deprecated. Use outcome_side (or book_side) instead. See Order direction. This field will not be removed before May 14, 2026.

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
yes_price_dollars
type:
string
required
Yes price in fixed-point dollars (4 decimals)

fill_count_fp
type:
string
required
Number of contracts filled in fixed-point (2 decimals)

remaining_count_fp
type:
string
required
Number of contracts remaining in fixed-point (2 decimals)

initial_count_fp
type:
string
required
Initial number of contracts in fixed-point (2 decimals)

taker_fill_cost_dollars
type:
string
required
Taker fill cost in fixed-point dollars (4 decimals)

maker_fill_cost_dollars
type:
string
required
Maker fill cost in fixed-point dollars (4 decimals)

taker_fees_dollars
type:
string
required
Taker fees in fixed-point dollars (4 decimals).

maker_fees_dollars
type:
string
required
Maker fees in fixed-point dollars (4 decimals).

client_order_id
type:
string
required
Client-provided order identifier

order_group_id
type:
string
Order group identifier, if applicable

self_trade_prevention_type
type:
enum
Self-trade prevention type

Available options: taker_at_cross, maker
created_time
type:
string
required
deprecated
Deprecated - Order creation time in RFC3339 format. Use created_ts_ms instead.

created_ts_ms
type:
integer
required
Order creation time as a Unix timestamp in milliseconds

last_update_time
type:
string
deprecated
Deprecated - Last update time in RFC3339 format. Use last_updated_ts_ms instead.

last_updated_ts_ms
type:
integer
Last update time as a Unix timestamp in milliseconds

expiration_time
type:
string
deprecated
Deprecated - Order expiration time in RFC3339 format. Use expiration_ts_ms instead.

expiration_ts_ms
type:
integer
Order expiration time as a Unix timestamp in milliseconds

subaccount_number
type:
integer
Subaccount number (0 for primary, 1-32 for subaccounts)