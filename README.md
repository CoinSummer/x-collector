# X Collector

A CLI tool for collecting tweets from X/Twitter API v2, designed for OpenClaw integration.

## Features

- **Get User Tweets**: Fetch recent tweets from any public user
- **Get Single Tweet**: Retrieve a specific tweet by ID
- **Search Tweets**: Search with X query operators
- **Collect All Tweets**: Full timeline collection with pagination
- **Adaptive Rate Limiting**: Automatically adjusts request speed based on API quota
- **Progress Persistence**: Resume interrupted collections
- **Multiple Output Formats**: JSON, JSONL, or Markdown

## Installation

```bash
# Clone the repository
cd /path/to/x-collector

# Install with pip (development mode)
pip install -e .

# Or install dependencies manually
pip install httpx pyyaml click rich
```

## Quick Start

### 1. Configure API Credentials

Create the config file:

```bash
x-collector config init
```

This creates `~/.openclaw/x-collector.yaml`. Edit it with your X Bearer Token:

```yaml
x:
  bearer_token: "YOUR_BEARER_TOKEN_HERE"
```

### 2. Get Your Bearer Token

1. Go to [X Developer Portal](https://developer.twitter.com/en/portal/dashboard)
2. Create a project and app (or use existing)
3. Navigate to "Keys and tokens"
4. Generate and copy the Bearer Token

### 3. Start Collecting

```bash
# Get recent tweets from a user
x-collector get-tweets elonmusk --limit 50

# Get a specific tweet
x-collector get-tweet 1234567890

# Search tweets
x-collector search "bitcoin" --limit 100

# Collect ALL tweets from a user
x-collector collect-all elonmusk --output ./elon_data
```

## Commands

### `get-tweets`

Fetch recent tweets from a user.

```bash
x-collector get-tweets <username> [OPTIONS]

Options:
  -l, --limit INTEGER     Maximum tweets to fetch (default: 100)
  --since-id TEXT         Only fetch tweets after this ID
  --until-id TEXT         Only fetch tweets before this ID
  -o, --output TEXT       Output file path
  -f, --format [json|jsonl|markdown]  Output format (default: json)
```

Examples:

```bash
# Get 50 recent tweets
x-collector get-tweets elonmusk --limit 50

# Save to file as markdown
x-collector get-tweets elonmusk --output tweets.md --format markdown

# Get tweets since a specific ID
x-collector get-tweets elonmusk --since-id 1234567890
```

### `get-tweet`

Get a single tweet by ID.

```bash
x-collector get-tweet <tweet_id> [OPTIONS]

Options:
  -o, --output TEXT       Output file path
  -f, --format [json|markdown]  Output format (default: json)
```

Examples:

```bash
x-collector get-tweet 1234567890
x-collector get-tweet 1234567890 --format markdown
```

### `search`

Search for tweets matching a query.

```bash
x-collector search <query> [OPTIONS]

Options:
  -l, --limit INTEGER     Maximum tweets to fetch (default: 100)
  --since-id TEXT         Only fetch tweets after this ID
  --until-id TEXT         Only fetch tweets before this ID
  -o, --output TEXT       Output file path
  -f, --format [json|jsonl|markdown]  Output format (default: json)
```

X search operators:

| Operator | Description | Example |
|----------|-------------|---------|
| `from:` | Tweets from user | `from:elonmusk` |
| `to:` | Replies to user | `to:elonmusk` |
| `#hashtag` | Contains hashtag | `#bitcoin` |
| `"phrase"` | Exact phrase | `"to the moon"` |
| `lang:` | Language | `lang:en` |
| `-word` | Exclude word | `-retweet` |

Examples:

```bash
# Search for bitcoin tweets
x-collector search "bitcoin" --limit 100

# Search tweets from a specific user about crypto
x-collector search "from:elonmusk crypto"

# Search with multiple operators
x-collector search "#AI lang:en -filter:retweets"
```

### `collect-all`

Collect complete tweet history from a user.

```bash
x-collector collect-all <username> [OPTIONS]

Options:
  -o, --output TEXT       Output directory (default: ./x_data)
  -f, --format [json|jsonl|markdown]  Output format (default: json)
  -m, --max-tweets INTEGER  Maximum tweets to collect
  --since-id TEXT         Only collect tweets after this ID
  --until-id TEXT         Only collect tweets before this ID
  --resume/--no-resume    Resume from last progress (default: resume)
```

Features:

- **Automatic pagination**: Handles X's pagination automatically
- **Rate limit handling**: Waits when approaching API limits
- **Progress saving**: Saves progress to resume if interrupted
- **Batch files**: Saves tweets in batches plus a combined file

Examples:

```bash
# Collect all tweets (may take hours for prolific accounts)
x-collector collect-all elonmusk --output ./elon_data

# Collect with limit
x-collector collect-all elonmusk --max-tweets 1000

# Collect in JSONL format (streaming-friendly)
x-collector collect-all elonmusk --format jsonl
```

Output structure:

```
./x_data/
├── batch_0001.json      # First batch
├── batch_0002.json      # Second batch
├── ...
├── all_tweets.json      # Combined file
└── .progress.json       # Progress file (deleted on completion)
```

### `get-thread`

Get all tweets in a thread/conversation.

```bash
x-collector get-thread <conversation_id> [OPTIONS]

Options:
  -o, --output TEXT       Output file path
  -f, --format [json|markdown]  Output format (default: json)
```

### `config`

Manage configuration.

```bash
# Create default config file
x-collector config init

# Show current configuration
x-collector config show

# Validate configuration
x-collector config validate
```

## Configuration

Configuration file location: `~/.openclaw/x-collector.yaml`

Full configuration options:

```yaml
x:
  # Required: X API v2 Bearer Token
  bearer_token: "AAAA..."

rate_limit:
  # Seconds between requests (normal mode)
  safe_delay: 0.7

  # Seconds between requests (approaching limit)
  slow_delay: 2.0

  # Slow down when remaining requests < this
  safe_threshold: 10

  # Wait for reset when remaining < this
  critical_threshold: 2

collection:
  # Max tweets per API request (max 100)
  max_results_per_page: 100

  # HTTP timeout in seconds
  timeout: 30

  # User agent string
  user_agent: "XCollector/0.1.0"

output:
  # Default format: json, jsonl, markdown
  format: "json"

  # Include referenced tweets
  include_referenced: true
```

### Environment Variables

Environment variables can override config file values:

| Variable | Description |
|----------|-------------|
| `X_BEARER_TOKEN` | X API Bearer Token (overrides config file) |
| `X_COLLECTOR_CONFIG` | Path to config file (overrides default path) |

## Rate Limiting

X API v2 has strict rate limits. This tool implements adaptive rate limiting:

### Rate Limit Strategy

1. **Normal Mode** (`remaining > safe_threshold`)
   - Wait `safe_delay` seconds between requests
   - Default: 0.7 seconds

2. **Slow Mode** (`remaining < safe_threshold`)
   - Wait `slow_delay` seconds between requests
   - Default: 2.0 seconds

3. **Critical Mode** (`remaining < critical_threshold`)
   - Wait for rate limit window to reset
   - Automatically resumes after reset

### API Tier Limits

| Tier | User Tweets | Search |
|------|-------------|--------|
| Basic | ~15/15min | ~450/15min |
| Pro | 300/15min | 450/15min |
| Enterprise | Higher | Higher |

The collector reads the `x-rate-limit-remaining` header from API responses to adapt in real-time.

## Output Formats

### JSON

```json
{
  "username": "elonmusk",
  "collected_at": "2024-01-15T10:30:00",
  "total_count": 100,
  "tweets": [
    {
      "id": "1234567890",
      "text": "Tweet content here",
      "created_at": "2024-01-15T09:00:00",
      "metrics": {
        "like_count": 1000,
        "retweet_count": 500
      }
    }
  ]
}
```

### JSONL (JSON Lines)

```
{"id": "1234567890", "text": "Tweet 1", ...}
{"id": "1234567891", "text": "Tweet 2", ...}
```

### Markdown

```markdown
# @elonmusk X Archive

**Collected:** 2024-01-15 10:30
**Total Tweets:** 100

---

### 2024-01-15 09:00

Tweet content here

*1000 likes, 500 RTs*

[View on X](https://x.com/elonmusk/status/1234567890)

---
```

## Python API

You can also use the collector as a Python library:

```python
import asyncio
from x_collector import XCollector, XConfig

async def main():
    # Load config
    config = XConfig.load()
    collector = XCollector(config)

    # Get recent tweets
    tweets = await collector.get_user_tweets("elonmusk", limit=50)
    for tweet in tweets:
        print(f"{tweet.created_at}: {tweet.text[:100]}")

    # Get a single tweet
    tweet = await collector.get_tweet("1234567890")
    print(tweet.to_json())

    # Search
    results = await collector.search_tweets("bitcoin", limit=100)
    print(f"Found {len(results)} tweets")

    # Collect all (generator)
    async for batch in collector.collect_all("elonmusk", max_tweets=1000):
        print(f"Got batch of {len(batch)} tweets")

asyncio.run(main())
```

## OpenClaw Integration

This skill is designed to work with OpenClaw. To use it:

1. Install the skill:
   ```bash
   pip install -e /path/to/x-collector
   ```

2. Configure credentials:
   ```bash
   x-collector config init
   # Edit ~/.openclaw/x-collector.yaml
   ```

3. Use in OpenClaw:
   ```
   > Collect the last 100 tweets from @elonmusk

   OpenClaw will invoke: x-collector get-tweets elonmusk --limit 100
   ```

## Troubleshooting

### "bearer_token not configured"

Make sure you've created the config file and added your token:

```bash
x-collector config init
# Edit ~/.openclaw/x-collector.yaml with your token
x-collector config validate
```

### "Rate limited (429)"

The collector will automatically wait and retry. If you're hitting limits frequently:

1. Increase `safe_delay` in config
2. Lower `safe_threshold` for earlier slowdown
3. Consider upgrading your API tier

### "User not found (404)"

- Check the username is correct (without @)
- Ensure the account is public
- Verify your Bearer Token has correct permissions

### Collection interrupted

Just run the same command again. Progress is automatically saved and resumed.

```bash
# Will resume from where it left off
x-collector collect-all elonmusk --output ./data
```

## License

MIT License
