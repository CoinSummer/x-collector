"""X API v2 collector.

This module provides the main XCollector class for interacting
with X/Twitter API v2 to collect tweets.

Features:
- Get tweets from a user's timeline
- Get a single tweet by ID
- Search tweets
- Collect all tweets (full timeline with pagination)
- Automatic rate limiting
- Progress persistence for resume

Example:
    ```python
    from x_collector import XCollector, XConfig

    config = XConfig.load()
    collector = XCollector(config)

    # Get recent tweets
    tweets = await collector.get_user_tweets("elonmusk", limit=100)

    # Collect all tweets
    async for batch in collector.collect_all("elonmusk"):
        print(f"Collected batch of {len(batch)} tweets")
    ```
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, AsyncIterator

import httpx

from x_collector.config import XConfig
from x_collector.rate_limiter import RateLimiter
from x_collector.models import Tweet, TweetCollection, XUser


logger = logging.getLogger(__name__)


class XAPIError(Exception):
    """X API error.

    Attributes:
        status_code: HTTP status code
        message: Error message
        reset_time: Seconds until rate limit resets (for 429 errors)
    """

    def __init__(self, status_code: int, message: str, reset_time: int = 0):
        self.status_code = status_code
        self.message = message
        self.reset_time = reset_time
        super().__init__(f"X API Error {status_code}: {message}")


class XCollector:
    """X API v2 collector.

    Provides methods to collect tweets from X/Twitter API v2 with
    automatic rate limiting and pagination support.

    Attributes:
        config: XConfig instance
        rate_limiter: RateLimiter instance
    """

    API_BASE = "https://api.twitter.com/2"

    # Tweet fields to request
    TWEET_FIELDS = [
        "id",
        "text",
        "created_at",
        "author_id",
        "conversation_id",
        "in_reply_to_user_id",
        "referenced_tweets",
        "attachments",
        "entities",
        "public_metrics",
        "possibly_sensitive",
        "lang",
        "source",
    ]

    # User fields for author info
    USER_FIELDS = [
        "id",
        "name",
        "username",
        "created_at",
        "description",
        "public_metrics",
        "verified",
    ]

    # Expansion fields
    EXPANSIONS = [
        "author_id",
        "referenced_tweets.id",
        "referenced_tweets.id.author_id",
        "attachments.media_keys",
    ]

    # Media fields
    MEDIA_FIELDS = [
        "type",
        "url",
        "preview_image_url",
        "alt_text",
    ]

    def __init__(self, config: Optional[XConfig] = None):
        """Initialize X collector.

        Args:
            config: X configuration (loads from file if None)
        """
        self.config = config or XConfig.load()
        self.rate_limiter = RateLimiter(self.config.rate_limit)

        # Caches
        self._user_cache: dict[str, XUser] = {}
        self._referenced_tweets: dict[str, Tweet] = {}

        # Stats
        self._request_count = 0
        self._tweet_count = 0
        self._error_count = 0

    @property
    def bearer_token(self) -> str:
        """Get X Bearer Token."""
        if not self.config.bearer_token:
            raise XAPIError(401, "bearer_token not configured")
        return self.config.bearer_token

    async def _make_request(
        self,
        endpoint: str,
        params: Optional[dict] = None,
    ) -> dict:
        """Make authenticated request to X API.

        Args:
            endpoint: API endpoint (without base URL)
            params: Query parameters

        Returns:
            JSON response

        Raises:
            XAPIError: On API error
        """
        url = f"{self.API_BASE}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.bearer_token}",
            "User-Agent": self.config.collection.user_agent,
        }

        async with httpx.AsyncClient(timeout=self.config.collection.timeout) as client:
            response = await client.get(url, headers=headers, params=params)
            self._request_count += 1

            # Update rate limiter
            remaining = int(response.headers.get("x-rate-limit-remaining", 1500))
            reset_time = int(response.headers.get("x-rate-limit-reset", 0))
            self.rate_limiter.update(remaining, reset_time)

            if response.status_code == 429:
                # Rate limited
                reset_seconds = reset_time - int(datetime.now().timestamp())
                raise XAPIError(429, f"Rate limited. Reset in {reset_seconds}s", reset_seconds)

            if response.status_code != 200:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("detail", response.text)
                self._error_count += 1
                raise XAPIError(response.status_code, error_msg)

            return response.json()

    async def get_user(self, username: str) -> XUser:
        """Get user information by username.

        Args:
            username: X username (without @)

        Returns:
            XUser instance

        Raises:
            XAPIError: If user not found
        """
        # Check cache
        if username in self._user_cache:
            return self._user_cache[username]

        logger.info(f"Looking up user @{username}")

        data = await self._make_request(
            f"/users/by/username/{username}",
            params={"user.fields": ",".join(self.USER_FIELDS)},
        )

        user_data = data.get("data", {})
        if not user_data:
            raise XAPIError(404, f"User @{username} not found")

        user = XUser.from_api(user_data)
        self._user_cache[username] = user

        logger.info(
            f"Found user: {user.name} (@{user.username}) "
            f"ID={user.id}, Tweets={user.tweet_count}"
        )

        return user

    async def get_tweet(self, tweet_id: str) -> Tweet:
        """Get a single tweet by ID.

        Args:
            tweet_id: Tweet ID

        Returns:
            Tweet instance

        Raises:
            XAPIError: If tweet not found
        """
        logger.info(f"Fetching tweet {tweet_id}")

        # Wait for rate limit
        await self.rate_limiter.wait()

        data = await self._make_request(
            f"/tweets/{tweet_id}",
            params={
                "tweet.fields": ",".join(self.TWEET_FIELDS),
                "user.fields": ",".join(self.USER_FIELDS),
                "expansions": ",".join(self.EXPANSIONS),
                "media.fields": ",".join(self.MEDIA_FIELDS),
            },
        )

        tweet_data = data.get("data", {})
        if not tweet_data:
            raise XAPIError(404, f"Tweet {tweet_id} not found")

        includes = data.get("includes", {})
        tweet = Tweet.from_api(tweet_data, includes)
        self._tweet_count += 1

        return tweet

    async def get_user_tweets(
        self,
        username: str,
        limit: int = 100,
        since_id: Optional[str] = None,
        until_id: Optional[str] = None,
    ) -> TweetCollection:
        """Get recent tweets from a user.

        Args:
            username: X username (without @)
            limit: Maximum tweets to return (default 100)
            since_id: Only return tweets after this ID
            until_id: Only return tweets before this ID

        Returns:
            TweetCollection with tweets
        """
        user = await self.get_user(username)
        collection = TweetCollection(username=username)

        pagination_token = None
        collected = 0

        while collected < limit:
            # Wait for rate limit
            await self.rate_limiter.wait()

            per_page = min(100, limit - collected)
            params = {
                "tweet.fields": ",".join(self.TWEET_FIELDS),
                "user.fields": ",".join(self.USER_FIELDS),
                "expansions": ",".join(self.EXPANSIONS),
                "media.fields": ",".join(self.MEDIA_FIELDS),
                "max_results": per_page,
            }

            if pagination_token:
                params["pagination_token"] = pagination_token
            if since_id:
                params["since_id"] = since_id
            if until_id:
                params["until_id"] = until_id

            try:
                data = await self._make_request(f"/users/{user.id}/tweets", params=params)
            except XAPIError as e:
                if e.status_code == 429:
                    await self.rate_limiter.wait_for_reset()
                    continue
                raise

            tweets_data = data.get("data", [])
            includes = data.get("includes", {})
            meta = data.get("meta", {})

            if not tweets_data:
                break

            for tweet_data in tweets_data:
                tweet = Tweet.from_api(tweet_data, includes)
                tweet.author = user
                collection.add(tweet)
                collected += 1
                self._tweet_count += 1

            logger.info(f"Collected {collected}/{limit} tweets from @{username}")

            pagination_token = meta.get("next_token")
            if not pagination_token:
                break

        return collection

    async def search_tweets(
        self,
        query: str,
        limit: int = 100,
        since_id: Optional[str] = None,
        until_id: Optional[str] = None,
    ) -> TweetCollection:
        """Search for tweets matching a query.

        Note: Requires elevated API access for full-archive search.
        Basic access only allows recent tweets (last 7 days).

        Args:
            query: Search query (supports X search operators)
            limit: Maximum tweets to return
            since_id: Only return tweets after this ID
            until_id: Only return tweets before this ID

        Returns:
            TweetCollection with matching tweets
        """
        collection = TweetCollection()
        pagination_token = None
        collected = 0

        while collected < limit:
            await self.rate_limiter.wait()

            per_page = min(100, limit - collected)
            params = {
                "query": query,
                "tweet.fields": ",".join(self.TWEET_FIELDS),
                "user.fields": ",".join(self.USER_FIELDS),
                "expansions": ",".join(self.EXPANSIONS),
                "media.fields": ",".join(self.MEDIA_FIELDS),
                "max_results": per_page,
            }

            if pagination_token:
                params["next_token"] = pagination_token
            if since_id:
                params["since_id"] = since_id
            if until_id:
                params["until_id"] = until_id

            try:
                data = await self._make_request("/tweets/search/recent", params=params)
            except XAPIError as e:
                if e.status_code == 429:
                    await self.rate_limiter.wait_for_reset()
                    continue
                raise

            tweets_data = data.get("data", [])
            includes = data.get("includes", {})
            meta = data.get("meta", {})

            if not tweets_data:
                break

            for tweet_data in tweets_data:
                tweet = Tweet.from_api(tweet_data, includes)
                collection.add(tweet)
                collected += 1
                self._tweet_count += 1

            logger.info(f"Search found {collected} tweets for query: {query[:50]}...")

            pagination_token = meta.get("next_token")
            if not pagination_token:
                break

        return collection

    async def get_thread(self, conversation_id: str) -> TweetCollection:
        """Get all tweets in a thread/conversation.

        Args:
            conversation_id: The conversation ID (usually the first tweet's ID)

        Returns:
            TweetCollection with thread tweets
        """
        return await self.search_tweets(f"conversation_id:{conversation_id}", limit=100)

    async def collect_all(
        self,
        username: str,
        since_id: Optional[str] = None,
        until_id: Optional[str] = None,
        max_tweets: Optional[int] = None,
        progress_file: Optional[Path] = None,
    ) -> AsyncIterator[TweetCollection]:
        """Collect all tweets from a user's timeline.

        This is a generator that yields batches of tweets as they're collected.
        Supports resume via progress_file.

        Args:
            username: X username (without @)
            since_id: Only return tweets after this ID
            until_id: Only return tweets before this ID
            max_tweets: Maximum total tweets (None = all)
            progress_file: Path to save progress for resume

        Yields:
            TweetCollection for each batch
        """
        user = await self.get_user(username)

        # Load progress if resuming
        pagination_token = None
        total_collected = 0

        if progress_file and progress_file.exists():
            try:
                with open(progress_file, "r") as f:
                    progress = json.load(f)
                pagination_token = progress.get("next_token")
                total_collected = progress.get("total_collected", 0)
                since_id = since_id or progress.get("since_id")
                logger.info(f"Resuming from progress file: {total_collected} tweets collected")
            except Exception as e:
                logger.warning(f"Could not load progress file: {e}")

        batch_num = 0
        start_time = datetime.now()
        estimated_total = user.tweet_count

        while True:
            if max_tweets is not None and total_collected >= max_tweets:
                logger.info(f"Reached max_tweets limit ({max_tweets})")
                break

            batch_num += 1

            # Progress logging
            if batch_num > 1:
                elapsed = (datetime.now() - start_time).total_seconds()
                rate = total_collected / max(1, elapsed) * 60
                remaining = estimated_total - total_collected
                eta = remaining / max(1, rate)
                logger.info(
                    f"Progress: {total_collected}/{estimated_total} tweets "
                    f"({rate:.0f}/min, ETA: {eta:.1f} min)"
                )

            # Wait for rate limit
            await self.rate_limiter.wait()

            per_page = self.config.collection.max_results_per_page
            if max_tweets:
                per_page = min(per_page, max_tweets - total_collected)

            params = {
                "tweet.fields": ",".join(self.TWEET_FIELDS),
                "user.fields": ",".join(self.USER_FIELDS),
                "expansions": ",".join(self.EXPANSIONS),
                "media.fields": ",".join(self.MEDIA_FIELDS),
                "max_results": per_page,
            }

            if pagination_token:
                params["pagination_token"] = pagination_token
            if since_id:
                params["since_id"] = since_id
            if until_id:
                params["until_id"] = until_id

            try:
                data = await self._make_request(f"/users/{user.id}/tweets", params=params)
            except XAPIError as e:
                if e.status_code == 429:
                    await self.rate_limiter.wait_for_reset()
                    continue
                raise

            tweets_data = data.get("data", [])
            includes = data.get("includes", {})
            meta = data.get("meta", {})

            if not tweets_data:
                logger.info("No more tweets found")
                break

            # Create batch collection
            batch = TweetCollection(username=username)
            for tweet_data in tweets_data:
                tweet = Tweet.from_api(tweet_data, includes)
                tweet.author = user
                batch.add(tweet)
                self._tweet_count += 1

            total_collected += len(batch)
            logger.info(
                f"Batch {batch_num}: {len(batch)} tweets "
                f"(total: {total_collected}, rate_limit: {self.rate_limiter.state.remaining})"
            )

            # Save progress
            pagination_token = meta.get("next_token")
            if progress_file:
                progress_file.parent.mkdir(parents=True, exist_ok=True)
                with open(progress_file, "w") as f:
                    json.dump({
                        "username": username,
                        "next_token": pagination_token,
                        "total_collected": total_collected,
                        "since_id": since_id,
                        "last_batch": datetime.utcnow().isoformat(),
                        "oldest_id": batch.oldest_id,
                        "newest_id": batch.newest_id,
                    }, f, indent=2)

            yield batch

            if not pagination_token:
                logger.info("Reached end of timeline")
                break

        # Final stats
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"Collection complete: {total_collected} tweets in {batch_num} batches "
            f"({elapsed:.1f}s, {total_collected / max(1, elapsed) * 60:.0f} tweets/min)"
        )

        # Clean up progress file on successful completion
        if progress_file and progress_file.exists():
            progress_file.unlink()

    @property
    def stats(self) -> dict:
        """Get collector statistics."""
        return {
            "requests": self._request_count,
            "tweets_collected": self._tweet_count,
            "errors": self._error_count,
            "rate_limiter": self.rate_limiter.stats,
            "users_cached": len(self._user_cache),
        }
