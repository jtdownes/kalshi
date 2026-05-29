Quick Start: Market Data
Learn how to access real-time market data without authentication

Documentation Index
Fetch the complete documentation index at: https://docs.kalshi.com/llms.txt

Use this file to discover all available pages before exploring further.

This guide will walk you through accessing Kalshi’s public market data endpoints without authentication. You’ll learn how to retrieve series information, events, markets, and orderbook data for the popular “Who will have a higher net approval” market.
​
Making Unauthenticated Requests
Kalshi provides several public endpoints that don’t require API keys. These endpoints allow you to access market data directly from our production servers at https://external-api.kalshi.com/trade-api/v2.
Note about the API URL: Despite the “elections” subdomain, the production Trade API provides access to ALL Kalshi markets - not just election-related ones. This includes markets on economics, climate, technology, entertainment, and more.
No authentication headers are required for the endpoints in this guide. You can start making requests immediately!
​
Step 1: Get Series Information
Let’s start by fetching information about the KXHIGHNY series (Highest temperature in NYC today?). This series tracks the highest temperature recorded in Central Park, New York on a given day. We’ll use the Get Series endpoint.

Python

JavaScript

cURL
import requests

# Get series information for KXHIGHNY
url = "https://external-api.kalshi.com/trade-api/v2/series/KXHIGHNY"
response = requests.get(url)
series_data = response.json()

print(f"Series Title: {series_data['series']['title']}")
print(f"Frequency: {series_data['series']['frequency']}")
print(f"Category: {series_data['series']['category']}")
​
Step 2: Get Today’s Events and Markets
Now that we have the series information, let’s get the markets for this series. We’ll use the Get Markets endpoint with the series ticker filter to find all active markets. If there are no open markets today, remove status=open or use status=all to see the full series history.

Python

JavaScript
# Get all open markets for the KXHIGHNY series
markets_url = f"https://external-api.kalshi.com/trade-api/v2/markets?series_ticker=KXHIGHNY&status=open"
markets_response = requests.get(markets_url)
markets_data = markets_response.json()

print(f"\nActive markets in KXHIGHNY series:")
for market in markets_data['markets']:
    print(f"- {market['ticker']}: {market['title']}")
    print(f"  Event: {market['event_ticker']}")
    print(f"  Yes Price: ${market['yes_bid_dollars']} | Volume: {market['volume_fp']}")
    print()

# Get details for a specific event if you have its ticker
if markets_data['markets']:
    # Let's get details for the first market's event
    event_ticker = markets_data['markets'][0]['event_ticker']
    event_url = f"https://external-api.kalshi.com/trade-api/v2/events/{event_ticker}"
    event_response = requests.get(event_url)
    event_data = event_response.json()

    print(f"Event Details:")
    print(f"Title: {event_data['event']['title']}")
    print(f"Category: {event_data['event']['category']}")
You can view these markets in the Kalshi UI at: https://kalshi.com/markets/kxhighny
​
Step 3: Get Orderbook Data
Now let’s fetch the orderbook for a specific market to see the current bids and asks using the Get Market Orderbook endpoint. This snippet assumes you still have the markets_data from the previous step. If markets_data['markets'] is empty, pick a market from a different series or remove the status=open filter.

Python

JavaScript
# Get orderbook for a specific market
# Replace with an actual market ticker from the markets list
if not markets_data['markets']:
    raise ValueError("No open markets found. Try removing status=open or choose another series.")

market_ticker = markets_data['markets'][0]['ticker']
orderbook_url = f"https://external-api.kalshi.com/trade-api/v2/markets/{market_ticker}/orderbook"

orderbook_response = requests.get(orderbook_url)
orderbook_data = orderbook_response.json()

print(f"\nOrderbook for {market_ticker}:")
print("YES BIDS:")
for price_dollars, count_fp in orderbook_data['orderbook_fp']['yes_dollars'][:5]:  # Show top 5
    print(f"  Price: ${price_dollars}, Quantity: {count_fp}")

print("\nNO BIDS:")
for price_dollars, count_fp in orderbook_data['orderbook_fp']['no_dollars'][:5]:  # Show top 5
    print(f"  Price: ${price_dollars}, Quantity: {count_fp}")
​
Working with Large Datasets
The Kalshi API uses cursor-based pagination to handle large datasets efficiently. To learn more about navigating through paginated responses, see our Understanding Pagination guide.
​
Understanding Orderbook Responses
Kalshi’s orderbook structure is unique due to the nature of binary prediction markets. The API only returns bids (not asks) because of the reciprocal relationship between YES and NO positions. To learn more about orderbook responses and why they work this way, see our Orderbook Responses guide.
​
Next Steps
Now that you understand how to access market data without authentication, you can:
Explore other public series and events
Build real-time market monitoring tools
Create market analysis dashboards
Set up a WebSocket connection for live updates (requires authentication)
For authenticated endpoints that allow trading and portfolio management, check out our API Keys guide.