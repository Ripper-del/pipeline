import logging
import httpx

logger = logging.getLogger(__name__)


async def get_adspower_ws(api_url, profile_id):
    """Launches an AdsPower profile and extracts its Playwright WebSocket endpoint."""
    url = f"{api_url.rstrip('/')}/api/v1/browser/start?user_id={profile_id}"
    logger.info(f"Connecting to AdsPower profile via Local API: {url}")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, timeout=30)
            if resp.status_code == 200:
                resp_json = resp.json()
                if resp_json.get("code") == 0:
                    ws_data = resp_json.get("data", {}).get("ws", {})
                    ws_url = ws_data.get("playwright") or ws_data.get("puppeteer")
                    if ws_url:
                        return ws_url
                    else:
                        raise Exception("WebSocket connection details missing in AdsPower API response.")
                else:
                    raise Exception(f"AdsPower returned error: {resp_json.get('msg')}")
            else:
                raise Exception(f"Failed HTTP response: {resp.status_code} - {resp.text}")
        except Exception as e:
            logger.error(f"Error starting AdsPower browser: {e}")
            raise e


async def stop_adspower_profile(api_url, profile_id):
    """Stops the specified AdsPower browser profile."""
    url = f"{api_url.rstrip('/')}/api/v1/browser/stop?user_id={profile_id}"
    logger.info(f"Stopping AdsPower profile: {profile_id}")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, timeout=30)
            if resp.status_code == 200:
                logger.info("Profile closed successfully.")
            else:
                logger.warning(f"AdsPower responded with status {resp.status_code}")
        except Exception as e:
            logger.error(f"Error stopping AdsPower profile: {e}")
