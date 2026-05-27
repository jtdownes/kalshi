Connection Keep-Alive
WebSocket control frames for connection management.

Kalshi sends Ping frames (0x9) every 10 seconds with body heartbeat to maintain the connection. Clients should respond with Pong frames (0xA). Clients may also send Ping frames to which Kalshi will respond with Pong.

WSS
Documentation Index
Fetch the complete documentation index at: https://docs.kalshi.com/llms.txt

Use this file to discover all available pages before exploring further.

Messages

Ping

Pong

Ping

Pong

Security Schemes
apiKey
type:
apiKey
API key authentication required for WebSocket connections.
The API key should be provided during the WebSocket handshake.


Send
Ping
type:
string
Client sends Ping frame (0x9) to elicit Pong from Kalshi

Pong
type:
string
Client replies to Ping with Pong Frame (0xA)


Receive
Ping
type:
string
Kalshi sends Ping (0x9) with body 'heartbeat' to elicit Pong from client

Pong
type:
string
Kalshi responds to client Ping with Pong frame (0xA)