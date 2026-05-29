Market & Event Lifecycle
Market state changes and event creation notifications.

Requirements:

No additional channel-level authentication beyond the authenticated WebSocket connection
Receives all market and event lifecycle notifications (market_ticker filters are not supported)
Event creation notifications
Use case: Tracking market lifecycle including creation, de(activation), close date changes, determination, settlement, price level structure changes, and metadata updates

WSS
market_lifecycle_v2
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
Market Lifecycle V2
type:
object

hide 3 properties
Market lifecycle events (created, activated, deactivated, close_date_updated, determined, settled, price_level_structure_updated, metadata_updated)

type
type:
string
required
market_lifecycle_v2

sid
type:
integer
required
Server-generated subscription identifier (sid) used to identify the channel

msg
type:
object
required

hide 13 properties
event_type
type:
enum
required
Field to annotate which of the event type this event is for:

created - Market created
activated - Market activated
deactivated - Market deactivated
close_date_updated - Market close date updated
determined - Market determined
settled - Market settled
price_level_structure_updated - Market price level structure changed
metadata_updated - Market metadata updated (e.g. floor strike, yes_sub_title)
Available options: created, deactivated, activated, close_date_updated, determined, settled, price_level_structure_updated, metadata_updated
market_ticker
type:
string
required
Unique market identifier

Examples: FED-23DEC-T3.00, HIGHNY-22DEC23-B53.5
open_ts
type:
integer
Optional - This key will ONLY exist when the market is created. Unix timestamp for when the market opened (in seconds)

close_ts
type:
integer
Optional - This key will ONLY exist when the market is created OR when the close date is updated. Unix timestamp for when the market is scheduled to close (in seconds). Will be updated in case of early determination markets

result
type:
string
Optional - This key will ONLY exist when the market is determined. Result of the market

determination_ts
type:
integer
Optional - This key will ONLY exist when the market is determined. Unix timestamp for when the market is determined (in seconds)

settlement_value
type:
string
Optional - This key will ONLY exist when the market is determined. Settlement value of the market in fixed-point dollars (e.g. "0.5000")

settled_ts
type:
integer
Optional - This key will ONLY exist when the market is settled. Unix timestamp for when the market is settled (in seconds)

is_deactivated
type:
boolean
Optional - This key will ONLY exist when the market is paused/unpaused. Boolean flag to indicate if trading is paused on an open market. This should only be interpreted for an open market

price_level_structure
type:
enum
Optional - This key will exist when the market is created or when the price level structure is updated. The price level structure of the market

Available options: linear_cent, deci_cent, tapered_deci_cent
floor_strike
type:
number
Optional - This key will ONLY exist for metadata_updated events. The updated floor strike value for the market

yes_sub_title
type:
string
Optional - This key will ONLY exist for metadata_updated events. The updated yes subtitle for the market

additional_metadata
type:
object

hide 13 properties
Optional - This key will be emitted when the market is created

name
type:
string
title
type:
string
yes_sub_title
type:
string
no_sub_title
type:
string
rules_primary
type:
string
rules_secondary
type:
string
can_close_early
type:
boolean
event_ticker
type:
string
expected_expiration_ts
type:
integer
strike_type
type:
string
floor_strike
type:
number
cap_strike
type:
number
custom_strike
type:
object
Event Lifecycle
type:
object

hide 3 properties
Event creation notification

type
type:
string
required
event_lifecycle

sid
type:
integer
required
Server-generated subscription identifier (sid) used to identify the channel

msg
type:
object
required

hide 7 properties
event_ticker
type:
string
required
Unique identifier for the event being created

title
type:
string
required
Title of event

subtitle
type:
string
required
Subtitle of event

collateral_return_type
type:
enum
required
Collateral return type, MECNET or DIRECNET of the event. Empty if there is no collateral return scheme for the event

Available options: MECNET, DIRECNET,
series_ticker
type:
string
required
Series ticker for the event

strike_date
type:
integer
Optional - Unix timestamp to indicate the strike date of the event if there is one

strike_period
type:
string
Optional - String to indicate the strike period of the event if there is one