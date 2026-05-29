Orderbook Updates
Real-time orderbook price level changes. Provides incremental updates to maintain a live orderbook.

Requirements:

Authentication required
Market specification required:
Use market_ticker (string) for a single market
Use market_tickers (array of strings) for multiple markets
market_id/market_ids are not supported for this channel
Sends orderbook_snapshot first, then incremental orderbook_delta updates
Supports update_subscription with add_markets / delete_markets / get_snapshot actions
get_snapshot returns an orderbook_snapshot for the requested market_tickers without modifying the subscription
Use case: Building and maintaining a real-time orderbook

WSS
orderbook_delta
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
Orderbook Snapshot
type:
object

hide 4 properties
Complete view of the order book's aggregated price levels

type
type:
string
required
orderbook_snapshot

sid
type:
integer
required
Server-generated subscription identifier (sid) used to identify the channel

seq
type:
integer
required
Sequential number that should be checked if you want to guarantee you received all the messages. Used for snapshot/delta consistency

msg
type:
object
required

hide 4 properties
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

yes_dollars_fp
type:
array

hide 1 property
Optional - This key will not exist if there are no Yes offers in the orderbook.
Price levels represented as [price_in_dollars, contract_count_fp].
Format: [price_in_dollars, contract_count_fp]

item
type:
array

hide 1 property
item
type:
string
no_dollars_fp
type:
array

hide 1 property
Optional - Same format as "yes_dollars_fp" but for the NO side of the orderbook.
This key will not exist if there are no No offers in the orderbook.
Format: [price_in_dollars, contract_count_fp]

item
type:
array

hide 1 property
item
type:
string
Orderbook Delta
type:
object

hide 4 properties
Update to be applied to the current order book view

type
type:
string
required
orderbook_delta

sid
type:
integer
required
Server-generated subscription identifier (sid) used to identify the channel

seq
type:
integer
required
Sequential number that should be checked if you want to guarantee you received all the messages. Used for snapshot/delta consistency

msg
type:
object
required

hide 9 properties
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
Price level in dollars

delta_fp
type:
string
required
Fixed-point contract delta (2 decimals)

side
type:
enum
required
Market side

Available options: yes, no
client_order_id
type:
string
Optional - Present only when you caused this orderbook change.
Contains the client_order_id of your order that triggered this delta.

subaccount
type:
integer
Optional - Present only when you caused this orderbook change and are using subaccounts.
Contains the subaccount number of your order that triggered this delta.

ts
type:
string
deprecated
Deprecated - Optional timestamp for when the orderbook change was recorded (RFC3339). Use ts_ms instead.

ts_ms
type:
integer
Optional - Unix timestamp for when the orderbook change was recorded (in milliseconds)