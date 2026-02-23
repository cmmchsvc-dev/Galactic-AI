"""
Galactic AI -- Social Media Skill (Phase 3 migration)
Twitter/X posting via tweepy and Reddit posting via praw.
All blocking API calls are wrapped in run_in_executor for async safety.
"""

import asyncio
import os

from skills.base import GalacticSkill


class SocialMediaSkill(GalacticSkill):
    """Twitter/X and Reddit integration for Galactic AI."""

    skill_name  = "social_media"
    version     = "1.1.2"
    author      = "Galactic AI"
    description = "Twitter/X and Reddit integration."
    category    = "social"
    icon        = "\U0001f4f1"

    # Legacy name for web_deck compat
    name = "SocialMedia"

    def __init__(self, core):
        super().__init__(core)

        # Lazy-initialized clients (created on first use)
        self._twitter_client = None       # tweepy.Client (v2 API)
        self._twitter_api = None          # tweepy.API (v1.1 -- media uploads)
        self._twitter_auth = None         # OAuth1UserHandler
        self._twitter_user_id = None      # Cached authenticated user ID
        self._reddit = None               # praw.Reddit instance

    # ── GalacticSkill: tool definitions ──────────────────────────────────

    def get_tools(self):
        return {
            "post_tweet": {
                "description": "Post a tweet to X/Twitter. Max 280 characters.",
                "parameters": {"type": "object", "properties": {
                    "text": {"type": "string", "description": "Tweet text (max 280 chars)"},
                    "reply_to": {"type": "string", "description": "Tweet ID to reply to (optional)"},
                    "media_path": {"type": "string", "description": "Path to image/video to attach (optional)"},
                }, "required": ["text"]},
                "fn": self._tool_post_tweet
            },
            "read_mentions": {
                "description": "Read recent @mentions on X/Twitter.",
                "parameters": {"type": "object", "properties": {
                    "count": {"type": "number", "description": "Number of mentions to fetch (default: 10)"},
                }},
                "fn": self._tool_read_mentions
            },
            "read_dms": {
                "description": "Read recent direct messages on X/Twitter.",
                "parameters": {"type": "object", "properties": {
                    "count": {"type": "number", "description": "Number of DMs to fetch (default: 10)"},
                }},
                "fn": self._tool_read_dms
            },
            "post_reddit": {
                "description": "Post to a subreddit on Reddit. Supports text posts and link posts.",
                "parameters": {"type": "object", "properties": {
                    "subreddit": {"type": "string", "description": "Subreddit name (without r/)"},
                    "title": {"type": "string", "description": "Post title"},
                    "body": {"type": "string", "description": "Post body text (for text posts)"},
                    "url": {"type": "string", "description": "URL (for link posts)"},
                    "flair": {"type": "string", "description": "Flair text (optional)"},
                }, "required": ["subreddit", "title"]},
                "fn": self._tool_post_reddit
            },
            "read_reddit_inbox": {
                "description": "Read Reddit inbox messages (replies, mentions, DMs).",
                "parameters": {"type": "object", "properties": {
                    "count": {"type": "number", "description": "Number of messages to fetch (default: 10)"},
                }},
                "fn": self._tool_read_reddit_inbox
            },
            "reply_reddit": {
                "description": "Reply to a Reddit comment or post.",
                "parameters": {"type": "object", "properties": {
                    "thing_id": {"type": "string", "description": "Reddit fullname ID of the thing to reply to (e.g. t1_abc123 for comment, t3_abc123 for post)"},
                    "body": {"type": "string", "description": "Reply text (Markdown supported)"},
                }, "required": ["thing_id", "body"]},
                "fn": self._tool_reply_reddit
            },
            "post_tweet_browser": {
                "description": "Post a single tweet on X.com using browser automation (no API key needed). Requires the Playwright browser to be started first.",
                "parameters": {"type": "object", "properties": {
                    "text": {"type": "string", "description": "Tweet text"},
                    "media_path": {"type": "string", "description": "Local path to image or video to attach (optional)"},
                }, "required": ["text"]},
                "fn": self._tool_post_tweet_browser
            },
            "post_thread_browser": {
                "description": "Post a multi-tweet thread on X.com using browser automation (no API key needed). Requires the Playwright browser to be started first.",
                "parameters": {"type": "object", "properties": {
                    "tweets": {"type": "array", "items": {"type": "string"}, "description": "List of tweet texts in order (first item = Tweet 1, etc.)"},
                    "media_path": {"type": "string", "description": "Local path to image or video to attach to Tweet 1 (optional)"},
                }, "required": ["tweets"]},
                "fn": self._tool_post_thread_browser
            },
        }

    # ── Tool handlers ────────────────────────────────────────────────────

    async def _tool_post_tweet(self, args):
        result = await self.post_tweet(
            text=args.get('text', ''),
            reply_to=args.get('reply_to'),
            media_path=args.get('media_path')
        )
        if result.get('status') == 'success':
            return f"[TWITTER] Tweet posted! ID: {result.get('tweet_id', '?')} — {result.get('url', '')}"
        return f"[ERROR] post_tweet: {result.get('message', 'unknown error')}"

    async def _tool_read_mentions(self, args):
        result = await self.read_mentions(count=int(args.get('count', 10)))
        if result.get('status') == 'success':
            mentions = result.get('mentions', [])
            if not mentions:
                return "[TWITTER] No recent mentions."
            lines = [f"[TWITTER] {len(mentions)} mention(s):"]
            for m in mentions:
                lines.append(f"  @{m.get('author', '?')} (ID: {m.get('id', '?')}): {m.get('text', '')[:200]}")
            return "\n".join(lines)
        return f"[ERROR] read_mentions: {result.get('message', 'unknown error')}"

    async def _tool_read_dms(self, args):
        result = await self.read_dms(count=int(args.get('count', 10)))
        if result.get('status') == 'success':
            dms = result.get('messages', [])
            if not dms:
                return "[TWITTER] No recent DMs."
            lines = [f"[TWITTER] {len(dms)} DM(s):"]
            for d in dms:
                lines.append(f"  From {d.get('sender', '?')}: {d.get('text', '')[:200]}")
            return "\n".join(lines)
        return f"[ERROR] read_dms: {result.get('message', 'unknown error')}"

    async def _tool_post_reddit(self, args):
        result = await self.post_reddit(
            subreddit=args.get('subreddit', ''),
            title=args.get('title', ''),
            body=args.get('body'),
            url=args.get('url'),
            flair=args.get('flair')
        )
        if result.get('status') == 'success':
            return f"[REDDIT] Post created! URL: {result.get('url', '?')}"
        return f"[ERROR] post_reddit: {result.get('message', 'unknown error')}"

    async def _tool_read_reddit_inbox(self, args):
        result = await self.read_reddit_inbox(count=int(args.get('count', 10)))
        if result.get('status') == 'success':
            messages = result.get('messages', [])
            if not messages:
                return "[REDDIT] Inbox empty."
            lines = [f"[REDDIT] {len(messages)} message(s):"]
            for m in messages:
                lines.append(f"  [{m.get('type', '?')}] u/{m.get('author', '?')}: {m.get('subject', '')[:60]} — {m.get('body', '')[:150]}")
            return "\n".join(lines)
        return f"[ERROR] read_reddit_inbox: {result.get('message', 'unknown error')}"

    async def _tool_reply_reddit(self, args):
        result = await self.reply_reddit(
            thing_id=args.get('thing_id', ''),
            body=args.get('body', '')
        )
        if result.get('status') == 'success':
            return f"[REDDIT] Reply posted! ID: {result.get('comment_id', '?')}"
        return f"[ERROR] reply_reddit: {result.get('message', 'unknown error')}"

    async def _tool_post_tweet_browser(self, args):
        result = await self.post_tweet_browser(
            text=args.get('text', ''),
            media_path=args.get('media_path')
        )
        if result.get('status') == 'success':
            return f"[TWITTER] Tweet posted via browser! URL: {result.get('url', '?')}"
        return f"[ERROR] post_tweet_browser: {result.get('message', 'unknown error')}"

    async def _tool_post_thread_browser(self, args):
        tweets = args.get('tweets', [])
        if not tweets:
            return "[ERROR] post_thread_browser: no tweets provided"
        result = await self.post_thread_browser(
            tweets=tweets,
            media_path=args.get('media_path')
        )
        if result.get('status') == 'success':
            return f"[TWITTER] Thread posted via browser! {result.get('tweet_count', 0)} tweets. URL: {result.get('url', '?')}"
        return f"[ERROR] post_thread_browser: {result.get('message', 'unknown error')}"

    # ══════════════════════════════════════════════════════════════════════
    #  TWITTER / X  (copied verbatim from plugins/social_media.py)
    # ══════════════════════════════════════════════════════════════════════

    def _init_twitter(self):
        """Lazy-initialize tweepy Client + v1.1 API from config.
        Returns (client, api) or raises on missing dependency / config.
        """
        if self._twitter_client is not None:
            return self._twitter_client, self._twitter_api

        try:
            import tweepy
        except ImportError:
            raise RuntimeError(
                "tweepy is not installed. Run: pip install tweepy"
            )

        tw_cfg = self.core.config.get("social_media", {}).get("twitter", {})
        consumer_key = tw_cfg.get("consumer_key", "")
        consumer_secret = tw_cfg.get("consumer_secret", "")
        access_token = tw_cfg.get("access_token", "")
        access_token_secret = tw_cfg.get("access_token_secret", "")

        if not all([consumer_key, consumer_secret, access_token, access_token_secret]):
            raise RuntimeError(
                "Twitter API credentials are incomplete. "
                "Set consumer_key, consumer_secret, access_token, and "
                "access_token_secret under social_media.twitter in config.yaml"
            )

        # v2 Client -- tweets, mentions, DMs
        self._twitter_client = tweepy.Client(
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            access_token=access_token,
            access_token_secret=access_token_secret,
            wait_on_rate_limit=True,
        )

        # v1.1 API via OAuth1UserHandler -- required for media uploads
        self._twitter_auth = tweepy.OAuth1UserHandler(
            consumer_key, consumer_secret,
            access_token, access_token_secret,
        )
        self._twitter_api = tweepy.API(self._twitter_auth, wait_on_rate_limit=True)

        return self._twitter_client, self._twitter_api

    def _get_twitter_user_id(self):
        """Return the authenticated user's Twitter ID (cached after first call)."""
        if self._twitter_user_id is not None:
            return self._twitter_user_id
        client, _ = self._init_twitter()
        me = client.get_me()
        if me and me.data:
            self._twitter_user_id = me.data.id
        return self._twitter_user_id

    # ── Tweets ────────────────────────────────────────────────────────────

    async def post_tweet(self, text, reply_to=None, media_path=None):
        """Post a tweet (optionally with media or as a reply).

        Args:
            text:       Tweet body (up to 280 chars for standard accounts).
            reply_to:   Tweet ID to reply to (optional).
            media_path: Local file path to an image/video to attach (optional).

        Returns:
            {"status": "success", "tweet_id": str, "url": str}
            {"status": "error", "message": str}
        """
        try:
            client, api = self._init_twitter()
        except RuntimeError as e:
            return {"status": "error", "message": str(e)}

        loop = asyncio.get_event_loop()

        try:
            media_ids = None

            # Upload media via v1.1 API if a file is provided
            if media_path:
                if not os.path.isfile(media_path):
                    return {"status": "error", "message": f"Media file not found: {media_path}"}

                media = await loop.run_in_executor(
                    None, lambda: api.media_upload(filename=media_path)
                )
                media_ids = [media.media_id]

            # Build create_tweet kwargs
            kwargs = {"text": text}
            if reply_to:
                kwargs["in_reply_to_tweet_id"] = reply_to
            if media_ids:
                kwargs["media_ids"] = media_ids

            response = await loop.run_in_executor(
                None, lambda: client.create_tweet(**kwargs)
            )

            tweet_id = str(response.data["id"])

            # Resolve the tweet URL (requires the username)
            try:
                me = await loop.run_in_executor(None, lambda: client.get_me())
                username = me.data.username if me and me.data else "i"
            except Exception:
                username = "i"

            url = f"https://x.com/{username}/status/{tweet_id}"

            await self.core.log(f"Tweet posted: {tweet_id}", priority=2, component="SocialMedia")
            return {"status": "success", "tweet_id": tweet_id, "url": url}

        except Exception as e:
            await self.core.log(f"Tweet failed: {e}", priority=1, component="SocialMedia")
            return {"status": "error", "message": str(e)}

    # ── Browser-based posting (no API key needed) ─────────────────────────

    async def post_tweet_browser(self, text, media_path=None):
        """Post a single tweet via Playwright browser automation.

        Does not require Twitter API credentials — uses the logged-in browser
        session. Requires BrowserProSkill to be started (browser must be open).

        Args:
            text:       Tweet body text.
            media_path: Local path to image/video to attach (optional).

        Returns:
            {"status": "success", "url": str}
            {"status": "error", "message": str}
        """
        browser = getattr(self.core, 'browser', None)
        if not browser or not getattr(browser, 'started', False):
            return {"status": "error", "message": "Browser not started. Use start_browser first."}

        try:
            # Navigate to compose
            nav = await browser.navigate("https://x.com/compose/post")
            if nav.get('status') == 'error':
                return nav

            # Wait for compose box (contenteditable div)
            COMPOSE = '[data-testid="tweetTextarea_0"]'
            await browser._get_page().wait_for_selector(COMPOSE, timeout=15000)

            # Type tweet text (type_text now handles contenteditable correctly)
            typed = await browser.type_text(COMPOSE, text)
            if typed.get('status') == 'error':
                return typed

            # Attach media if provided
            if media_path:
                if not os.path.isfile(media_path):
                    return {"status": "error", "message": f"Media file not found: {media_path}"}
                page = browser._get_page()
                file_input = await page.query_selector('input[data-testid="fileInput"]')
                if file_input:
                    await file_input.set_input_files(media_path)
                    await asyncio.sleep(3)  # Wait for upload

            # Click Post button
            POST_BTN = '[data-testid="tweetButtonInline"]'
            page = browser._get_page()
            await page.wait_for_selector(POST_BTN, timeout=10000)
            await page.click(POST_BTN)

            # Wait for compose dialog to close (indicates success)
            await asyncio.sleep(2)
            current_url = page.url

            await self.core.log("Tweet posted via browser", priority=2, component="SocialMedia")
            return {"status": "success", "url": current_url}

        except Exception as e:
            await self.core.log(f"Browser tweet failed: {e}", priority=1, component="SocialMedia")
            return {"status": "error", "message": str(e)}

    async def post_thread_browser(self, tweets, media_path=None):
        """Post a multi-tweet thread via Playwright browser automation.

        Does not require Twitter API credentials — uses the logged-in browser
        session. Requires BrowserProSkill to be started (browser must be open).

        Args:
            tweets:     List of tweet text strings in order.
            media_path: Local path to image/video to attach to Tweet 1 (optional).

        Returns:
            {"status": "success", "tweet_count": int, "url": str}
            {"status": "error", "message": str}
        """
        if not tweets:
            return {"status": "error", "message": "No tweets provided"}

        browser = getattr(self.core, 'browser', None)
        if not browser or not getattr(browser, 'started', False):
            return {"status": "error", "message": "Browser not started. Use start_browser first."}

        try:
            # Navigate to compose
            nav = await browser.navigate("https://x.com/compose/post")
            if nav.get('status') == 'error':
                return nav

            COMPOSE_0 = '[data-testid="tweetTextarea_0"]'
            ADD_BTN   = '[data-testid="addButton"]'
            POST_ALL  = '[data-testid="tweetButton"]'

            page = browser._get_page()
            await page.wait_for_selector(COMPOSE_0, timeout=15000)

            # Type Tweet 1
            await browser.type_text(COMPOSE_0, tweets[0])

            # Attach media to Tweet 1 if provided
            if media_path:
                if not os.path.isfile(media_path):
                    return {"status": "error", "message": f"Media file not found: {media_path}"}
                file_input = await page.query_selector('input[data-testid="fileInput"]')
                if file_input:
                    await file_input.set_input_files(media_path)
                    await asyncio.sleep(3)  # Wait for upload

            # Add remaining tweets
            for i, tweet_text in enumerate(tweets[1:], start=2):
                # Click "Add another post" (the + button)
                await page.wait_for_selector(ADD_BTN, timeout=10000)
                await page.click(ADD_BTN)
                await asyncio.sleep(0.5)

                # Find the new compose box (nth textarea)
                compose_n = f'[data-testid="tweetTextarea_{i - 1}"]'
                try:
                    await page.wait_for_selector(compose_n, timeout=5000)
                    await browser.type_text(compose_n, tweet_text)
                except Exception:
                    # Fallback: use last focused contenteditable
                    await page.keyboard.type(tweet_text, delay=10)

            # Click "Post all"
            await page.wait_for_selector(POST_ALL, timeout=10000)
            await page.click(POST_ALL)
            await asyncio.sleep(2)

            current_url = page.url
            await self.core.log(f"Thread of {len(tweets)} tweets posted via browser", priority=2, component="SocialMedia")
            return {"status": "success", "tweet_count": len(tweets), "url": current_url}

        except Exception as e:
            await self.core.log(f"Browser thread failed: {e}", priority=1, component="SocialMedia")
            return {"status": "error", "message": str(e)}

    # ── Mentions ──────────────────────────────────────────────────────────

    async def read_mentions(self, count=10):
        """Fetch recent mentions for the authenticated user.

        Returns:
            {"status": "success", "mentions": [{"id", "text", "author_id", "created_at"}, ...]}
            {"status": "error", "message": str}
        """
        try:
            client, _ = self._init_twitter()
        except RuntimeError as e:
            return {"status": "error", "message": str(e)}

        loop = asyncio.get_event_loop()

        try:
            user_id = await loop.run_in_executor(None, self._get_twitter_user_id)
            if not user_id:
                return {"status": "error", "message": "Could not resolve authenticated Twitter user ID"}

            response = await loop.run_in_executor(
                None,
                lambda: client.get_users_mentions(
                    id=user_id,
                    max_results=min(count, 100),
                    tweet_fields=["created_at", "author_id", "text"],
                ),
            )

            mentions = []
            if response and response.data:
                for tweet in response.data:
                    mentions.append({
                        "id": str(tweet.id),
                        "text": tweet.text,
                        "author_id": str(tweet.author_id),
                        "created_at": str(tweet.created_at) if tweet.created_at else None,
                    })

            await self.core.log(f"Fetched {len(mentions)} mention(s)", priority=2, component="SocialMedia")
            return {"status": "success", "mentions": mentions}

        except Exception as e:
            await self.core.log(f"Read mentions failed: {e}", priority=1, component="SocialMedia")
            return {"status": "error", "message": str(e)}

    # ── Direct Messages ───────────────────────────────────────────────────

    async def read_dms(self, count=10):
        """Fetch recent direct message events.

        Returns:
            {"status": "success", "messages": [{"id", "text", "sender_id"}, ...]}
            {"status": "error", "message": str}
        """
        try:
            client, _ = self._init_twitter()
        except RuntimeError as e:
            return {"status": "error", "message": str(e)}

        loop = asyncio.get_event_loop()

        try:
            response = await loop.run_in_executor(
                None,
                lambda: client.get_direct_message_events(
                    max_results=min(count, 100),
                    dm_event_fields=["id", "text", "sender_id"],
                ),
            )

            messages = []
            if response and response.data:
                for dm in response.data:
                    messages.append({
                        "id": str(dm.id),
                        "text": dm.text if hasattr(dm, "text") else "",
                        "sender_id": str(dm.sender_id) if hasattr(dm, "sender_id") else "",
                    })

            await self.core.log(f"Fetched {len(messages)} DM(s)", priority=2, component="SocialMedia")
            return {"status": "success", "messages": messages}

        except Exception as e:
            await self.core.log(f"Read DMs failed: {e}", priority=1, component="SocialMedia")
            return {"status": "error", "message": str(e)}

    async def send_dm(self, recipient_id, text):
        """Send a direct message to a Twitter user.

        Args:
            recipient_id: The target user's Twitter ID.
            text:         Message body.

        Returns:
            {"status": "success", "dm_id": str}
            {"status": "error", "message": str}
        """
        try:
            client, _ = self._init_twitter()
        except RuntimeError as e:
            return {"status": "error", "message": str(e)}

        loop = asyncio.get_event_loop()

        try:
            response = await loop.run_in_executor(
                None,
                lambda: client.create_direct_message(
                    participant_id=recipient_id,
                    text=text,
                ),
            )

            dm_id = str(response.data["id"]) if response and response.data else "unknown"

            await self.core.log(
                f"DM sent to {recipient_id}: {text[:40]}...",
                priority=2, component="SocialMedia",
            )
            return {"status": "success", "dm_id": dm_id}

        except Exception as e:
            await self.core.log(f"Send DM failed: {e}", priority=1, component="SocialMedia")
            return {"status": "error", "message": str(e)}

    # ══════════════════════════════════════════════════════════════════════
    #  REDDIT  (copied verbatim from plugins/social_media.py)
    # ══════════════════════════════════════════════════════════════════════

    def _init_reddit(self):
        """Lazy-initialize praw.Reddit from config.
        Returns the Reddit instance or raises on missing dependency / config.
        """
        if self._reddit is not None:
            return self._reddit

        try:
            import praw  # noqa: F811
        except ImportError:
            raise RuntimeError(
                "praw is not installed. Run: pip install praw"
            )

        rd_cfg = self.core.config.get("social_media", {}).get("reddit", {})
        client_id = rd_cfg.get("client_id", "")
        client_secret = rd_cfg.get("client_secret", "")
        username = rd_cfg.get("username", "")
        password = rd_cfg.get("password", "")
        user_agent = rd_cfg.get("user_agent", "GalacticAI/1.0")

        if not all([client_id, client_secret, username, password]):
            raise RuntimeError(
                "Reddit API credentials are incomplete. "
                "Set client_id, client_secret, username, and password "
                "under social_media.reddit in config.yaml"
            )

        import praw as _praw
        self._reddit = _praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            username=username,
            password=password,
            user_agent=user_agent,
        )
        return self._reddit

    # ── Posts ─────────────────────────────────────────────────────────────

    async def post_reddit(self, subreddit, title, body=None, url=None, flair=None):
        """Submit a text or link post to a subreddit.

        Args:
            subreddit: Target subreddit name (without r/ prefix).
            title:     Post title.
            body:      Self-text body (for text posts).
            url:       Link URL (for link posts -- mutually exclusive with body).
            flair:     Optional flair text.

        Returns:
            {"status": "success", "post_id": str, "url": str}
            {"status": "error", "message": str}
        """
        try:
            reddit = self._init_reddit()
        except RuntimeError as e:
            return {"status": "error", "message": str(e)}

        loop = asyncio.get_event_loop()

        try:
            def _submit():
                sub = reddit.subreddit(subreddit)
                kwargs = {"title": title}

                if url:
                    kwargs["url"] = url
                else:
                    kwargs["selftext"] = body or ""

                if flair:
                    # Attempt to find matching flair template
                    try:
                        choices = list(sub.flair.link_templates)
                        match = next(
                            (f for f in choices if f["text"].lower() == flair.lower()),
                            None,
                        )
                        if match:
                            kwargs["flair_id"] = match["id"]
                            kwargs["flair_text"] = match["text"]
                        else:
                            kwargs["flair_text"] = flair
                    except Exception:
                        kwargs["flair_text"] = flair

                submission = sub.submit(**kwargs)
                return submission

            submission = await loop.run_in_executor(None, _submit)

            post_id = str(submission.id)
            post_url = f"https://www.reddit.com{submission.permalink}"

            await self.core.log(
                f"Reddit post submitted: r/{subreddit} -- {title[:50]}",
                priority=2, component="SocialMedia",
            )
            return {"status": "success", "post_id": post_id, "url": post_url}

        except Exception as e:
            await self.core.log(f"Reddit post failed: {e}", priority=1, component="SocialMedia")
            return {"status": "error", "message": str(e)}

    # ── Inbox ─────────────────────────────────────────────────────────────

    async def read_reddit_inbox(self, count=10):
        """Read the authenticated user's Reddit inbox.

        Returns:
            {"status": "success", "messages": [
                {"id", "type", "body", "author", "subject", "subreddit"}, ...
            ]}
            {"status": "error", "message": str}
        """
        try:
            reddit = self._init_reddit()
        except RuntimeError as e:
            return {"status": "error", "message": str(e)}

        loop = asyncio.get_event_loop()

        try:
            def _read_inbox():
                items = []
                for item in reddit.inbox.all(limit=count):
                    entry = {
                        "id": str(item.id) if hasattr(item, "id") else str(getattr(item, "name", "")),
                        "body": str(item.body) if hasattr(item, "body") else "",
                        "author": str(item.author) if item.author else "[deleted]",
                    }

                    # Determine message type
                    fullname = getattr(item, "name", "") or ""
                    if fullname.startswith("t1_"):
                        entry["type"] = "comment"
                    elif fullname.startswith("t4_"):
                        entry["type"] = "message"
                    else:
                        entry["type"] = "unknown"

                    entry["subject"] = str(getattr(item, "subject", ""))
                    entry["subreddit"] = str(item.subreddit) if hasattr(item, "subreddit") and item.subreddit else ""

                    items.append(entry)
                return items

            messages = await loop.run_in_executor(None, _read_inbox)

            await self.core.log(
                f"Fetched {len(messages)} Reddit inbox item(s)",
                priority=2, component="SocialMedia",
            )
            return {"status": "success", "messages": messages}

        except Exception as e:
            await self.core.log(f"Reddit inbox read failed: {e}", priority=1, component="SocialMedia")
            return {"status": "error", "message": str(e)}

    # ── Replies ───────────────────────────────────────────────────────────

    async def reply_reddit(self, thing_id, body):
        """Reply to a Reddit comment (t1_) or post (t3_).

        Args:
            thing_id: Reddit fullname (e.g. "t1_abc123" or "t3_xyz456")
                      or just the base36 ID -- the method will attempt lookup.
            body:     Reply markdown text.

        Returns:
            {"status": "success", "reply_id": str}
            {"status": "error", "message": str}
        """
        try:
            reddit = self._init_reddit()
        except RuntimeError as e:
            return {"status": "error", "message": str(e)}

        loop = asyncio.get_event_loop()

        try:
            def _reply():
                import praw.models  # noqa: F811

                # Normalise thing_id -- accept "t1_xxx", "t3_xxx", or bare "xxx"
                tid = thing_id.strip()

                if tid.startswith("t1_"):
                    # Comment reply
                    comment = reddit.comment(id=tid.replace("t1_", ""))
                    reply = comment.reply(body=body)
                    return str(reply.id) if reply else "unknown"
                elif tid.startswith("t3_"):
                    # Submission reply
                    submission = reddit.submission(id=tid.replace("t3_", ""))
                    reply = submission.reply(body=body)
                    return str(reply.id) if reply else "unknown"
                else:
                    # Best-effort: try as comment first, fall back to submission
                    try:
                        comment = reddit.comment(id=tid)
                        comment.refresh()  # Force-load to validate
                        reply = comment.reply(body=body)
                        return str(reply.id) if reply else "unknown"
                    except Exception:
                        submission = reddit.submission(id=tid)
                        reply = submission.reply(body=body)
                        return str(reply.id) if reply else "unknown"

            reply_id = await loop.run_in_executor(None, _reply)

            await self.core.log(
                f"Reddit reply posted on {thing_id}: {body[:40]}...",
                priority=2, component="SocialMedia",
            )
            return {"status": "success", "reply_id": reply_id}

        except Exception as e:
            await self.core.log(f"Reddit reply failed: {e}", priority=1, component="SocialMedia")
            return {"status": "error", "message": str(e)}

    # ══════════════════════════════════════════════════════════════════════
    #  SKILL LIFECYCLE
    # ══════════════════════════════════════════════════════════════════════

    async def run(self):
        """Background loop -- keeps the skill registered and alive."""
        await self.core.log("Social Media skill active.", priority=2, component="SocialMedia")
        while self.enabled:
            await asyncio.sleep(30)
