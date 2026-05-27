Order Group Updates
Real-time order group lifecycle and limit updates. Requires authentication.

Requirements:

Authentication required
Market specification ignored
Updates sent when order groups are created, triggered, reset, deleted, or have limits updated
Use case: Tracking order group lifecycle and limits

WSS
order_group_updates
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
Order Group Updates
type:
object

hide 4 properties
Order group lifecycle and limit updates for authenticated user

type
type:
string
required
order_group_updates

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
event_type
type:
enum
required
Order group event type

Available options: created, triggered, reset, deleted, limit_updated
order_group_id
type:
string
required
Order group identifier

contracts_limit_fp
type:
string
Updated contracts limit in fixed-point (2 decimals). Present for "created" and "limit_updated" events only.

ts_ms
type:
integer
required
Matching engine timestamp at which the event was processed, as Unix epoch milliseconds.