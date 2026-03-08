"""Data models for X Collector.

These models represent X/Twitter data in a normalized format,
making it easy to work with tweets regardless of API version.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum
import json


class TweetType(str, Enum):
    """Type of tweet."""
    TWEET = "tweet"
    RETWEET = "retweet"
    QUOTE = "quote"
    REPLY = "reply"


@dataclass
class XUser:
    """Twitter user information."""
    id: str
    username: str
    name: str
    description: str = ""
    created_at: Optional[datetime] = None
    verified: bool = False
    followers_count: int = 0
    following_count: int = 0
    tweet_count: int = 0

    @classmethod
    def from_api(cls, data: dict) -> "XUser":
        """Create from Twitter API v2 response.

        Args:
            data: User object from API response

        Returns:
            XUser instance
        """
        metrics = data.get("public_metrics", {})
        created_at = None
        if "created_at" in data:
            created_at = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))

        return cls(
            id=data.get("id", ""),
            username=data.get("username", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            created_at=created_at,
            verified=data.get("verified", False),
            followers_count=metrics.get("followers_count", 0),
            following_count=metrics.get("following_count", 0),
            tweet_count=metrics.get("tweet_count", 0),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "username": self.username,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "verified": self.verified,
            "followers_count": self.followers_count,
            "following_count": self.following_count,
            "tweet_count": self.tweet_count,
        }


@dataclass
class TweetMetrics:
    """Tweet engagement metrics."""
    retweet_count: int = 0
    reply_count: int = 0
    like_count: int = 0
    quote_count: int = 0
    bookmark_count: int = 0
    impression_count: int = 0

    @classmethod
    def from_api(cls, data: dict) -> "TweetMetrics":
        """Create from Twitter API v2 public_metrics."""
        return cls(
            retweet_count=data.get("retweet_count", 0),
            reply_count=data.get("reply_count", 0),
            like_count=data.get("like_count", 0),
            quote_count=data.get("quote_count", 0),
            bookmark_count=data.get("bookmark_count", 0),
            impression_count=data.get("impression_count", 0),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "retweet_count": self.retweet_count,
            "reply_count": self.reply_count,
            "like_count": self.like_count,
            "quote_count": self.quote_count,
            "bookmark_count": self.bookmark_count,
            "impression_count": self.impression_count,
        }

    @property
    def total_engagement(self) -> int:
        """Total engagement (likes + retweets + replies + quotes)."""
        return self.like_count + self.retweet_count + self.reply_count + self.quote_count


@dataclass
class TweetMedia:
    """Media attached to a tweet."""
    type: str  # photo, video, animated_gif
    url: Optional[str] = None
    preview_url: Optional[str] = None
    alt_text: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "type": self.type,
            "url": self.url,
            "preview_url": self.preview_url,
            "alt_text": self.alt_text,
        }


@dataclass
class Tweet:
    """Normalized tweet data.

    Attributes:
        id: Tweet ID
        text: Tweet text content
        author_id: Author user ID
        author: Author user info (if available)
        created_at: Tweet creation time
        tweet_type: Type of tweet (tweet, retweet, quote, reply)
        conversation_id: Thread/conversation ID
        in_reply_to_user_id: User ID being replied to (for replies)
        referenced_tweet_id: ID of referenced tweet (for quotes/retweets)
        referenced_tweet: The referenced tweet object (if available)
        metrics: Engagement metrics
        media: Attached media
        lang: Language code
        source: Client used to post
        url: Direct URL to tweet
    """
    id: str
    text: str
    author_id: str
    created_at: datetime
    tweet_type: TweetType = TweetType.TWEET
    conversation_id: Optional[str] = None
    in_reply_to_user_id: Optional[str] = None
    referenced_tweet_id: Optional[str] = None
    referenced_tweet: Optional["Tweet"] = None
    author: Optional[XUser] = None
    metrics: TweetMetrics = field(default_factory=TweetMetrics)
    media: list[TweetMedia] = field(default_factory=list)
    lang: str = ""
    source: str = ""
    raw_data: dict = field(default_factory=dict)

    @property
    def url(self) -> str:
        """Direct URL to this tweet."""
        username = self.author.username if self.author else "i"
        return f"https://x.com/{username}/status/{self.id}"

    @property
    def is_thread(self) -> bool:
        """Check if this tweet is part of a thread."""
        return self.conversation_id is not None and self.conversation_id != self.id

    @property
    def is_reply(self) -> bool:
        """Check if this is a reply."""
        return self.tweet_type == TweetType.REPLY

    @property
    def is_retweet(self) -> bool:
        """Check if this is a retweet."""
        return self.tweet_type == TweetType.RETWEET

    @property
    def is_quote(self) -> bool:
        """Check if this is a quote tweet."""
        return self.tweet_type == TweetType.QUOTE

    @classmethod
    def from_api(
        cls,
        data: dict,
        includes: Optional[dict] = None,
    ) -> "Tweet":
        """Create from Twitter API v2 response.

        Args:
            data: Tweet object from API response
            includes: Includes object with referenced data

        Returns:
            Tweet instance
        """
        includes = includes or {}

        # Parse creation time
        created_at = datetime.fromisoformat(
            data.get("created_at", datetime.utcnow().isoformat()).replace("Z", "+00:00")
        )

        # Determine tweet type
        tweet_type = TweetType.TWEET
        referenced_tweet_id = None
        referenced_tweets = data.get("referenced_tweets", [])
        for ref in referenced_tweets:
            if ref.get("type") == "retweeted":
                tweet_type = TweetType.RETWEET
                referenced_tweet_id = ref.get("id")
                break
            elif ref.get("type") == "quoted":
                tweet_type = TweetType.QUOTE
                referenced_tweet_id = ref.get("id")
            elif ref.get("type") == "replied_to":
                tweet_type = TweetType.REPLY
                referenced_tweet_id = ref.get("id")

        # Get author info from includes
        author = None
        author_id = data.get("author_id", "")
        for user_data in includes.get("users", []):
            if user_data.get("id") == author_id:
                author = XUser.from_api(user_data)
                break

        # Parse metrics
        metrics = TweetMetrics.from_api(data.get("public_metrics", {}))

        # Parse media
        media = []
        media_keys = data.get("attachments", {}).get("media_keys", [])
        for media_data in includes.get("media", []):
            if media_data.get("media_key") in media_keys:
                media.append(TweetMedia(
                    type=media_data.get("type", "photo"),
                    url=media_data.get("url"),
                    preview_url=media_data.get("preview_image_url"),
                    alt_text=media_data.get("alt_text"),
                ))

        return cls(
            id=data.get("id", ""),
            text=data.get("text", ""),
            author_id=author_id,
            created_at=created_at,
            tweet_type=tweet_type,
            conversation_id=data.get("conversation_id"),
            in_reply_to_user_id=data.get("in_reply_to_user_id"),
            referenced_tweet_id=referenced_tweet_id,
            author=author,
            metrics=metrics,
            media=media,
            lang=data.get("lang", ""),
            source=data.get("source", ""),
            raw_data=data,
        )

    def to_dict(self) -> dict:
        """Convert to dictionary (for JSON serialization)."""
        return {
            "id": self.id,
            "text": self.text,
            "author_id": self.author_id,
            "author": self.author.to_dict() if self.author else None,
            "created_at": self.created_at.isoformat(),
            "tweet_type": self.tweet_type.value,
            "conversation_id": self.conversation_id,
            "in_reply_to_user_id": self.in_reply_to_user_id,
            "referenced_tweet_id": self.referenced_tweet_id,
            "referenced_tweet": self.referenced_tweet.to_dict() if self.referenced_tweet else None,
            "metrics": self.metrics.to_dict(),
            "media": [m.to_dict() for m in self.media],
            "lang": self.lang,
            "source": self.source,
            "url": self.url,
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def to_markdown(self) -> str:
        """Convert to markdown format.

        Returns:
            Markdown-formatted tweet
        """
        lines = []

        # Header with date and type
        date_str = self.created_at.strftime("%Y-%m-%d %H:%M")
        type_indicator = ""
        if self.is_retweet:
            type_indicator = " [RT]"
        elif self.is_quote:
            type_indicator = " [Quote]"
        elif self.is_reply:
            type_indicator = " [Reply]"

        lines.append(f"### {date_str}{type_indicator}")
        lines.append("")

        # Tweet text
        lines.append(self.text)
        lines.append("")

        # Metrics
        if self.metrics.total_engagement > 0:
            metrics_parts = []
            if self.metrics.like_count:
                metrics_parts.append(f"{self.metrics.like_count} likes")
            if self.metrics.retweet_count:
                metrics_parts.append(f"{self.metrics.retweet_count} RTs")
            if self.metrics.reply_count:
                metrics_parts.append(f"{self.metrics.reply_count} replies")
            lines.append(f"*{', '.join(metrics_parts)}*")
            lines.append("")

        # URL
        lines.append(f"[View on X]({self.url})")
        lines.append("")
        lines.append("---")
        lines.append("")

        return "\n".join(lines)


@dataclass
class TweetCollection:
    """Collection of tweets with metadata.

    Attributes:
        tweets: List of tweets
        username: Twitter username collected from
        collected_at: When collection was performed
        total_count: Total tweets available (may be > len(tweets))
        oldest_id: ID of oldest tweet in collection
        newest_id: ID of newest tweet in collection
    """
    tweets: list[Tweet] = field(default_factory=list)
    username: str = ""
    collected_at: datetime = field(default_factory=datetime.utcnow)
    total_count: int = 0
    oldest_id: Optional[str] = None
    newest_id: Optional[str] = None

    def add(self, tweet: Tweet) -> None:
        """Add a tweet to the collection."""
        self.tweets.append(tweet)
        self.total_count = len(self.tweets)

        if self.oldest_id is None or tweet.id < self.oldest_id:
            self.oldest_id = tweet.id
        if self.newest_id is None or tweet.id > self.newest_id:
            self.newest_id = tweet.id

    def extend(self, tweets: list[Tweet]) -> None:
        """Add multiple tweets to the collection."""
        for tweet in tweets:
            self.add(tweet)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "username": self.username,
            "collected_at": self.collected_at.isoformat(),
            "total_count": self.total_count,
            "oldest_id": self.oldest_id,
            "newest_id": self.newest_id,
            "tweets": [t.to_dict() for t in self.tweets],
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def to_jsonl(self) -> str:
        """Convert to JSON Lines format (one tweet per line)."""
        lines = []
        for tweet in self.tweets:
            lines.append(json.dumps(tweet.to_dict(), ensure_ascii=False))
        return "\n".join(lines)

    def to_markdown(self) -> str:
        """Convert to markdown format."""
        lines = []

        # Header
        lines.append(f"# @{self.username} X Archive")
        lines.append("")
        lines.append(f"**Collected:** {self.collected_at.strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"**Total Tweets:** {self.total_count}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Tweets (newest first)
        sorted_tweets = sorted(self.tweets, key=lambda t: t.created_at, reverse=True)
        for tweet in sorted_tweets:
            lines.append(tweet.to_markdown())

        return "\n".join(lines)

    def filter_by_type(self, tweet_type: TweetType) -> "TweetCollection":
        """Filter tweets by type.

        Args:
            tweet_type: Type to filter by

        Returns:
            New TweetCollection with filtered tweets
        """
        filtered = TweetCollection(
            username=self.username,
            collected_at=self.collected_at,
        )
        filtered.extend([t for t in self.tweets if t.tweet_type == tweet_type])
        return filtered

    def filter_original(self) -> "TweetCollection":
        """Get only original tweets (no retweets, quotes, or replies).

        Returns:
            New TweetCollection with only original tweets
        """
        return self.filter_by_type(TweetType.TWEET)

    def __len__(self) -> int:
        return len(self.tweets)

    def __iter__(self):
        return iter(self.tweets)
