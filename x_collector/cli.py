"""Command-line interface for X Collector.

Usage:
    x-collector get-tweets <username> [--limit 100] [--output tweets.json]
    x-collector get-tweet <tweet_id> [--output tweet.json]
    x-collector search <query> [--limit 100] [--output results.json]
    x-collector collect-all <username> [--output ./data] [--format json]
    x-collector config --init
    x-collector config --show
    x-collector config --validate
"""

import asyncio
import sys
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.panel import Panel
from rich.syntax import Syntax

from x_collector.config import XConfig, ConfigError, DEFAULT_CONFIG_PATH
from x_collector.collector import XCollector, XAPIError
from x_collector.models import TweetCollection


console = Console()


def setup_logging(verbose: bool = False) -> None:
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )


def load_config(config_path: Optional[str] = None) -> XConfig:
    """Load and validate configuration."""
    path = Path(config_path) if config_path else None
    config = XConfig.load(path)

    errors = config.validate()
    if errors:
        console.print("[red]Configuration errors:[/red]")
        for error in errors:
            console.print(f"  - {error}")
        console.print(f"\nEdit config at: {config.config_path}")
        sys.exit(1)

    return config


def save_output(
    collection: TweetCollection,
    output: Optional[str],
    format: str,
) -> None:
    """Save collection to file or print to stdout."""
    if format == "json":
        content = collection.to_json()
    elif format == "jsonl":
        content = collection.to_jsonl()
    elif format == "markdown":
        content = collection.to_markdown()
    else:
        content = collection.to_json()

    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        console.print(f"[green]Saved to {path}[/green]")
    else:
        if format == "json":
            syntax = Syntax(content, "json", theme="monokai")
            console.print(syntax)
        else:
            console.print(content)


@click.group()
@click.option("--config", "-c", help="Path to config file")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def main(ctx: click.Context, config: Optional[str], verbose: bool) -> None:
    """X Collector - Collect tweets from X/Twitter API.

    A CLI tool for collecting tweets with rate limiting and pagination support.

    Configuration:
        Create ~/.openclaw/x-collector.yaml with your API credentials.
        Run 'x-collector config init' to create a template.

    Examples:
        x-collector get-tweets elonmusk --limit 50
        x-collector get-tweet 1234567890
        x-collector search "from:elonmusk bitcoin"
        x-collector collect-all elonmusk --output ./data
    """
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    ctx.obj["verbose"] = verbose
    setup_logging(verbose)


@main.command("get-tweets")
@click.argument("username")
@click.option("--limit", "-l", default=100, help="Maximum tweets to fetch")
@click.option("--since-id", help="Only fetch tweets after this ID")
@click.option("--until-id", help="Only fetch tweets before this ID")
@click.option("--output", "-o", help="Output file path")
@click.option("--format", "-f", type=click.Choice(["json", "jsonl", "markdown"]), default="json")
@click.pass_context
def get_tweets(
    ctx: click.Context,
    username: str,
    limit: int,
    since_id: Optional[str],
    until_id: Optional[str],
    output: Optional[str],
    format: str,
) -> None:
    """Get recent tweets from a user.

    Examples:
        x-collector get-tweets elonmusk
        x-collector get-tweets elonmusk --limit 50 --output tweets.json
        x-collector get-tweets elonmusk --format markdown
    """
    config = load_config(ctx.obj.get("config_path"))
    collector = XCollector(config)

    async def run():
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(f"Fetching tweets from @{username}...", total=None)

            try:
                collection = await collector.get_user_tweets(
                    username=username,
                    limit=limit,
                    since_id=since_id,
                    until_id=until_id,
                )
                progress.update(task, completed=True)
            except XAPIError as e:
                progress.stop()
                console.print(f"[red]Error: {e.message}[/red]")
                sys.exit(1)

        # Display summary
        console.print(Panel(
            f"[bold]@{username}[/bold]\n"
            f"Tweets: {len(collection)}\n"
            f"Newest: {collection.newest_id}\n"
            f"Oldest: {collection.oldest_id}",
            title="Collection Summary",
        ))

        save_output(collection, output, format)

    asyncio.run(run())


@main.command("get-tweet")
@click.argument("tweet_id")
@click.option("--output", "-o", help="Output file path")
@click.option("--format", "-f", type=click.Choice(["json", "markdown"]), default="json")
@click.pass_context
def get_tweet(
    ctx: click.Context,
    tweet_id: str,
    output: Optional[str],
    format: str,
) -> None:
    """Get a single tweet by ID.

    Examples:
        x-collector get-tweet 1234567890
        x-collector get-tweet 1234567890 --format markdown
    """
    config = load_config(ctx.obj.get("config_path"))
    collector = XCollector(config)

    async def run():
        try:
            tweet = await collector.get_tweet(tweet_id)
        except XAPIError as e:
            console.print(f"[red]Error: {e.message}[/red]")
            sys.exit(1)

        # Create single-tweet collection for output
        collection = TweetCollection()
        collection.add(tweet)

        # Display tweet
        console.print(Panel(
            f"[bold]{tweet.text}[/bold]\n\n"
            f"Author: @{tweet.author.username if tweet.author else tweet.author_id}\n"
            f"Date: {tweet.created_at.strftime('%Y-%m-%d %H:%M')}\n"
            f"Likes: {tweet.metrics.like_count} | RTs: {tweet.metrics.retweet_count}",
            title=f"Tweet {tweet_id}",
        ))

        save_output(collection, output, format)

    asyncio.run(run())


@main.command("search")
@click.argument("query")
@click.option("--limit", "-l", default=100, help="Maximum tweets to fetch")
@click.option("--since-id", help="Only fetch tweets after this ID")
@click.option("--until-id", help="Only fetch tweets before this ID")
@click.option("--output", "-o", help="Output file path")
@click.option("--format", "-f", type=click.Choice(["json", "jsonl", "markdown"]), default="json")
@click.pass_context
def search(
    ctx: click.Context,
    query: str,
    limit: int,
    since_id: Optional[str],
    until_id: Optional[str],
    output: Optional[str],
    format: str,
) -> None:
    """Search for tweets.

    Supports X search operators:
        from:username - Tweets from a user
        to:username - Replies to a user
        #hashtag - Contains hashtag
        "exact phrase" - Contains exact phrase

    Examples:
        x-collector search "bitcoin"
        x-collector search "from:elonmusk crypto" --limit 50
        x-collector search "#AI" --output ai_tweets.json
    """
    config = load_config(ctx.obj.get("config_path"))
    collector = XCollector(config)

    async def run():
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(f"Searching: {query[:50]}...", total=None)

            try:
                collection = await collector.search_tweets(
                    query=query,
                    limit=limit,
                    since_id=since_id,
                    until_id=until_id,
                )
                progress.update(task, completed=True)
            except XAPIError as e:
                progress.stop()
                console.print(f"[red]Error: {e.message}[/red]")
                sys.exit(1)

        console.print(f"[green]Found {len(collection)} tweets[/green]")
        save_output(collection, output, format)

    asyncio.run(run())


@main.command("collect-all")
@click.argument("username")
@click.option("--output", "-o", default="./x_data", help="Output directory")
@click.option("--format", "-f", type=click.Choice(["json", "jsonl", "markdown"]), default="json")
@click.option("--max-tweets", "-m", type=int, help="Maximum tweets to collect")
@click.option("--since-id", help="Only collect tweets after this ID")
@click.option("--until-id", help="Only collect tweets before this ID")
@click.option("--resume/--no-resume", default=True, help="Resume from last progress")
@click.pass_context
def collect_all(
    ctx: click.Context,
    username: str,
    output: str,
    format: str,
    max_tweets: Optional[int],
    since_id: Optional[str],
    until_id: Optional[str],
    resume: bool,
) -> None:
    """Collect all tweets from a user's timeline.

    This command fetches the complete tweet history with:
    - Automatic pagination
    - Rate limit handling
    - Progress saving for resume

    Examples:
        x-collector collect-all elonmusk
        x-collector collect-all elonmusk --output ./elon_tweets
        x-collector collect-all elonmusk --max-tweets 1000
    """
    config = load_config(ctx.obj.get("config_path"))
    collector = XCollector(config)

    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_file = output_dir / ".progress.json" if resume else None

    async def run():
        console.print(f"[bold]Collecting all tweets from @{username}[/bold]")
        console.print(f"Output directory: {output_dir}")

        all_tweets = TweetCollection(username=username)
        batch_num = 0

        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Collecting...", total=None)

                async for batch in collector.collect_all(
                    username=username,
                    since_id=since_id,
                    until_id=until_id,
                    max_tweets=max_tweets,
                    progress_file=progress_file,
                ):
                    batch_num += 1
                    all_tweets.extend(batch.tweets)

                    # Save batch
                    batch_file = output_dir / f"batch_{batch_num:04d}.{format}"
                    if format == "json":
                        content = batch.to_json()
                    elif format == "jsonl":
                        content = batch.to_jsonl()
                    else:
                        content = batch.to_markdown()

                    with open(batch_file, "w", encoding="utf-8") as f:
                        f.write(content)

                    progress.update(
                        task,
                        description=f"Collected {len(all_tweets)} tweets ({batch_num} batches)",
                    )

                progress.update(task, completed=True)

        except XAPIError as e:
            console.print(f"[red]Error: {e.message}[/red]")
            console.print("[yellow]Progress saved. Run again to resume.[/yellow]")
            sys.exit(1)
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted. Progress saved. Run again to resume.[/yellow]")
            sys.exit(1)

        # Save combined file
        combined_file = output_dir / f"all_tweets.{format}"
        if format == "json":
            content = all_tweets.to_json()
        elif format == "jsonl":
            content = all_tweets.to_jsonl()
        else:
            content = all_tweets.to_markdown()

        with open(combined_file, "w", encoding="utf-8") as f:
            f.write(content)

        # Summary
        console.print("\n" + "=" * 50)
        console.print(Panel(
            f"[bold green]Collection Complete![/bold green]\n\n"
            f"Username: @{username}\n"
            f"Tweets: {len(all_tweets)}\n"
            f"Batches: {batch_num}\n"
            f"Output: {combined_file}",
            title="Summary",
        ))

        # Stats table
        stats = collector.stats
        table = Table(title="Collection Stats")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        table.add_row("API Requests", str(stats["requests"]))
        table.add_row("Tweets Collected", str(stats["tweets_collected"]))
        table.add_row("Errors", str(stats["errors"]))
        table.add_row("Rate Limit Remaining", str(stats["rate_limiter"]["current_remaining"]))
        console.print(table)

    asyncio.run(run())


@main.command("get-thread")
@click.argument("conversation_id")
@click.option("--output", "-o", help="Output file path")
@click.option("--format", "-f", type=click.Choice(["json", "markdown"]), default="json")
@click.pass_context
def get_thread(
    ctx: click.Context,
    conversation_id: str,
    output: Optional[str],
    format: str,
) -> None:
    """Get all tweets in a thread/conversation.

    Examples:
        x-collector get-thread 1234567890
    """
    config = load_config(ctx.obj.get("config_path"))
    collector = XCollector(config)

    async def run():
        try:
            collection = await collector.get_thread(conversation_id)
        except XAPIError as e:
            console.print(f"[red]Error: {e.message}[/red]")
            sys.exit(1)

        console.print(f"[green]Found {len(collection)} tweets in thread[/green]")
        save_output(collection, output, format)

    asyncio.run(run())


@main.group("config")
def config_group() -> None:
    """Manage configuration."""
    pass


@config_group.command("init")
@click.option("--force", is_flag=True, help="Overwrite existing config")
def config_init(force: bool) -> None:
    """Create default configuration file.

    Creates ~/.openclaw/x-collector.yaml with placeholder values.
    """
    if DEFAULT_CONFIG_PATH.exists() and not force:
        console.print(f"[yellow]Config already exists at {DEFAULT_CONFIG_PATH}[/yellow]")
        console.print("Use --force to overwrite")
        return

    path = XConfig.create_default()
    console.print(f"[green]Created config at {path}[/green]")
    console.print("\nEdit the file to add your X Bearer Token:")
    console.print(f"  {path}")


@config_group.command("show")
def config_show() -> None:
    """Show current configuration."""
    try:
        config = XConfig.load()
    except ConfigError as e:
        console.print(f"[red]Error loading config: {e}[/red]")
        return

    console.print(Panel(
        f"Config file: {config.config_path}\n"
        f"Bearer token: {'[green]configured[/green]' if config.bearer_token else '[red]not set[/red]'}\n"
        f"Rate limit (safe delay): {config.rate_limit.safe_delay}s\n"
        f"Rate limit (slow delay): {config.rate_limit.slow_delay}s\n"
        f"Max results per page: {config.collection.max_results_per_page}\n"
        f"Output format: {config.output.format}",
        title="X Collector Configuration",
    ))


@config_group.command("validate")
def config_validate() -> None:
    """Validate configuration."""
    try:
        config = XConfig.load()
    except ConfigError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

    errors = config.validate()
    if errors:
        console.print("[red]Configuration errors:[/red]")
        for error in errors:
            console.print(f"  - {error}")
        sys.exit(1)

    console.print("[green]Configuration is valid![/green]")


if __name__ == "__main__":
    main()
