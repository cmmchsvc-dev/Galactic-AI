"""
Galactic AI — Social Media Plugin
Twitter/X posting via tweepy and Reddit posting via praw.
All blocking API calls are wrapped in run_in_executor for async safety.
"""

import asyncio
import os


class GalacticPlugin:
    def __init__(self, core):
        self.core = core
        self.name = "BasePlugin"
        self.enabled = True

    async def run(self):
        pass


class SocialMediaPlugin(GalacticPlugin):
    """Twitter/X and Reddit integration for Galactic AI."""

    def __init__(self, core):
        super().__init__(core)
        self.name = "SocialMedia"

        # Lazy-initialized clients (created on first use)
        self._twitter_client = None       # tweepy.Client (v2 API)
        self._twitter_api = None          # tweepy.API (v1.1 — media uploads)
        self._twitter_auth = None         # OAuth1UserHandler
        self._twitter_user_id = None      # Cached authenticated user ID
        self._reddit = None               # praw.Reddit instance

    # ══════════════════════════════════════════════════════════════════════
    #  TWITTER / X
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

        # v2 Client — tweets, mentions, DMs
        self._twitter_client = tweepy.Client(
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            access_token=access_token,
            access_token_secret=access_token_secret,
            wait_on_rate_limit=True,
        )

        # v1.1 API via OAuth1UserHandler — required for media uploads
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
    #  REDDIT
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
            url:       Link URL (for link posts — mutually exclusive with body).
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
                f"Reddit post submitted: r/{subreddit} — {title[:50]}",
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
                      or just the base36 ID — the method will attempt lookup.
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

                # Normalise thing_id — accept "t1_xxx", "t3_xxx", or bare "xxx"
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
    #  PLUGIN LIFECYCLE
    # ══════════════════════════════════════════════════════════════════════

    async def run(self):
        """Background loop — keeps the plugin registered and alive."""
        await self.core.log("Social Media plugin active.", priority=2, component="SocialMedia")
        while self.enabled:
            await asyncio.sleep(30)
