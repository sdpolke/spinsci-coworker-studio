"""Utility for getting a public tunnel URL at runtime.

Used when ``BACKEND_API_ENDPOINT`` is localhost / private — carriers like Twilio
cannot dial ``http://localhost``. We discover, in order:

1. cloudflared metrics (Docker ``cloudflared:2000``)
2. ngrok local agent API (``http://127.0.0.1:4040/api/tunnels``)
"""

import asyncio
import re
from typing import Optional
from urllib.parse import urlparse

import aiohttp
from loguru import logger

_NGROK_API_CANDIDATES = (
    "http://127.0.0.1:4040/api/tunnels",
    "http://localhost:4040/api/tunnels",
    # Host-run ngrok when the API itself runs inside Docker Desktop
    "http://host.docker.internal:4040/api/tunnels",
)


class TunnelURLProvider:
    """Provider for getting tunnel URLs from cloudflared or ngrok."""

    @classmethod
    async def get_tunnel_urls(cls) -> tuple[str, str]:
        """
        Get the tunnel URLs for external access.

        Returns:
            tuple[str, str]: (https_url, wss_url) - Both URLs include full protocol

        Raises:
            ValueError: If no tunnel URL can be determined
        """

        try:
            urls = await cls._get_cloudflared_urls()
            if urls:
                return urls
        except Exception as e:
            logger.warning(f"Failed to get tunnel URL from cloudflared: {e}")

        try:
            urls = await cls._get_ngrok_urls()
            if urls:
                return urls
        except Exception as e:
            logger.warning(f"Failed to get tunnel URL from ngrok: {e}")

        raise ValueError(
            "No tunnel URL available. Start ngrok (`ngrok http 8000`) or "
            "cloudflared, or set BACKEND_API_ENDPOINT to a publicly reachable HTTPS URL."
        )

    @classmethod
    async def _get_cloudflared_urls(cls) -> Optional[tuple[str, str]]:
        """
        Query cloudflared metrics endpoint to get the tunnel URLs.

        Returns:
            Optional[tuple[str, str]]: (https_url, wss_url) with full protocols, or None if not found
        """
        try:
            # Try to connect to cloudflared metrics endpoint
            # The service name in docker-compose is 'cloudflared'
            metrics_url = "http://cloudflared:2000/metrics"

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    metrics_url, timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status != 200:
                        logger.warning(
                            f"Cloudflared metrics returned status {response.status}"
                        )
                        return None

                    text = await response.text()

                    # Look for the tunnel URL in metrics
                    # Cloudflared exposes this in the userHostname metric
                    match = re.search(r'userHostname="([^"]+)"', text)
                    if match:
                        hostname = match.group(1)
                        # Remove https:// or wss:// if present
                        hostname = hostname.replace("https://", "").replace(
                            "wss://", ""
                        )
                        return "https://" + hostname, "wss://" + hostname

                    # Alternative: Look for trycloudflare.com domain
                    match = re.search(r"([a-z0-9-]+\.trycloudflare\.com)", text)
                    if match:
                        hostname = match.group(1)
                        hostname = hostname.replace("https://", "").replace(
                            "wss://", ""
                        )
                        return f"https://{hostname}", f"wss://{hostname}"

                    logger.warning("Could not find tunnel URL in cloudflared metrics")
                    return None

        except asyncio.TimeoutError:
            logger.warning("Timeout connecting to cloudflared metrics endpoint")
            return None
        except aiohttp.ClientError as e:
            logger.warning(f"Error connecting to cloudflared: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting cloudflared URL: {e}")
            return None

    @classmethod
    async def _get_ngrok_urls(cls) -> Optional[tuple[str, str]]:
        """Query the local ngrok agent API for a public HTTPS tunnel."""
        timeout = aiohttp.ClientTimeout(total=3)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for api_url in _NGROK_API_CANDIDATES:
                try:
                    async with session.get(api_url) as response:
                        if response.status != 200:
                            continue
                        payload = await response.json(content_type=None)
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                    continue

                tunnels = payload.get("tunnels") if isinstance(payload, dict) else None
                if not isinstance(tunnels, list):
                    continue

                https_url = cls._pick_ngrok_public_url(tunnels)
                if not https_url:
                    continue

                parsed = urlparse(https_url)
                if parsed.scheme != "https" or not parsed.netloc:
                    continue

                https = f"https://{parsed.netloc}"
                wss = f"wss://{parsed.netloc}"
                logger.info(f"Using ngrok tunnel URL: {https}")
                return https, wss

        logger.debug("No ngrok HTTPS tunnel found on local agent API")
        return None

    @staticmethod
    def _pick_ngrok_public_url(tunnels: list) -> Optional[str]:
        """Prefer an https public_url that looks like an ngrok edge."""
        https_urls: list[str] = []
        for tunnel in tunnels:
            if not isinstance(tunnel, dict):
                continue
            public_url = tunnel.get("public_url")
            if not isinstance(public_url, str):
                continue
            if public_url.startswith("https://"):
                https_urls.append(public_url.rstrip("/"))

        if not https_urls:
            return None

        # Prefer classic ngrok hostnames when multiple tunnels are open.
        for url in https_urls:
            host = urlparse(url).hostname or ""
            if (
                host.endswith(".ngrok-free.app")
                or host.endswith(".ngrok-free.dev")
                or host.endswith(".ngrok.io")
                or host.endswith(".ngrok.app")
            ):
                return url
        return https_urls[0]
