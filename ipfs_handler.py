from aiohttp import ClientSession, ClientTimeout
import asyncio
import json

def is_ipfs(url: str) -> bool:
    return 'ipfs' in url

def get_hash(url: str) -> str:
    """Gets CID from string containing an ipfs url

    Args:
        url (str): the url of the file

    Returns:
        str: the CID
    """
    split = url.split('/')[-1]
    if split.endswith('.ipfs.w3s.link'):
        split = split.split('.')[0]
    return split

class IPFSHandler:
    def __init__(self, timeout = 5):
        self.ipfs_gateways = {
            "ipfs_io": "https://ipfs.io/ipfs/",
            "dweb": "https://dweb.link/ipfs/"
        }
        self.session = None
        self._timeout = timeout

    async def _ensure_session(self):
        if self.session is None:
            self.session = ClientSession()
        return self.session

    def get_gateways(self, hash):
        return [f"{gateway}{hash}" for gateway in self.ipfs_gateways.values()]
    
    async def _fetch_from_gateway(self, gateway):
        timeout = ClientTimeout(total=self._timeout)  # 5 second timeout
        try:
            async with self.session.get(gateway, timeout=timeout) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    return None
        except Exception as e:
            return None
        
    async def fetch_from_gateways(self, gateways):
        
        tasks = [self._fetch_from_gateway(url) for url in gateways]
        
        for completed_task in asyncio.as_completed(tasks):
            result = await completed_task
            if result is not None:
                return result
                
        return None
    
    async def fetch(self, url):
        await self._ensure_session()
        result = None
        timeout = ClientTimeout(self._timeout)

        if is_ipfs(url):
            result = await self.fetch_from_gateways(self.get_gateways(get_hash(url)))
        else:
            async with self.session.get(url, timeout=timeout) as response:
                if response.status == 200:
                    result = await response.json()

        return result

    async def close(self):
        await self.session.close()
