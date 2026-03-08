"""X Collector - X/Twitter data collection for OpenClaw.

A CLI tool for collecting tweets from X/Twitter API v2.

Features:
- Get user tweets (with pagination)
- Get single tweet by ID
- Search tweets
- Collect all tweets from a user (full timeline)
- Adaptive rate limiting
- Progress persistence for resume

Usage:
    x-collector get-tweets <username> [--limit 100]
    x-collector get-tweet <tweet_id>
    x-collector search <query> [--limit 100]
    x-collector collect-all <username> [--output ./data]

Configuration:
    Create ~/.openclaw/x-collector.yaml with your API credentials.
"""

__version__ = "0.1.0"
__all__ = [
    "XCollector",
    "XConfig",
    "RateLimiter",
    "Tweet",
    "TweetCollection",
]

from x_collector.collector import XCollector
from x_collector.config import XConfig
from x_collector.rate_limiter import RateLimiter
from x_collector.models import Tweet, TweetCollection
