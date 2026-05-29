Multivariate Market & Event Lifecycle
Multivariate event (MVE) market state changes and event creation notifications.

Requirements:

No additional channel-level authentication beyond the authenticated WebSocket connection
Receives all multivariate market lifecycle notifications (market_ticker filters are not supported)
Only emits lifecycle updates for multivariate events
Event creation notifications
Use case: Tracking multivariate market lifecycle including creation, de(activation), close date changes, determination, settlement

WSS
multivariate_market_lifecycle
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
Multivariate Market Lifecycle
Multivariate market lifecycle events (created, activated, deactivated, close_date_updated, determined, settled)

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