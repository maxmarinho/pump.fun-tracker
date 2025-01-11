from dataclasses import dataclass
from solana.rpc.websocket_api import connect
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Commitment
import json
import asyncio

from anchorpy import Idl, Program, Provider, EventParser, Event
from solders.keypair import Keypair # type: ignore
from solders.pubkey import Pubkey # type: ignore
from solders.rpc.config import RpcTransactionLogsFilterMentions # type: ignore
from solders.rpc.responses import * # type: ignore

from termcolor import colored, cprint
from typing import Callable

import logging
import traceback

import asyncio
from aiohttp import ClientSession, ClientTimeout

from api.constants import TraderConfig

@dataclass
class TraderConfig:

    """
    Global config for the trader bot. will be refactored to a different file later. this will contain all the settings of the bot. 
    """

    # Program Account for pump fun exchange
    program_id = Pubkey.from_string("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")

    # Token Program for pump fun -> SPL?
    token_id = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")

    # RPC URLs
    rpc_url = 'https://api.mainnet-beta.solana.com'
    wss_url = 'wss://api.mainnet-beta.solana.com'

    # Filtering settings
    socials = ("telegram", "twitter", "website")

    # Default commitment for listening to events is confirmed
    commitment = "confirmed"

    # Wallet
    keypair = Keypair()  # random keypair for now

    # Test Settings
    run_time = 10000

    # Path to log file
    log_file = "logs/logs.log"
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    logging.basicConfig(filename=log_file,
                        filemode='w',
                        format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s', 
                        datefmt='%H:%M:%S', level=logging.INFO)


logger = logging.getLogger(__name__)

class TokenNotifier:

    def __init__(self, config = TraderConfig()) -> None:

        """
        Initializes the TokenNotifier instance with configuration and sets up connections.

        This method performs the following:
        - Sets up the trading bot configuration.
        - Initializes an asynchronous RPC client to connect to the Solana blockchain.
        - Configures the Anchor IDL client for program interaction.
        - Opens a file for error logging.
        - Initializes a default callback for handling token creation events.
        """

        self.config = config
        cprint("Initialized config.", "cyan", "on_white")

        # Connection to RPC
        self.client = AsyncClient(self.config.rpc_url)  
        cprint("Created Async RPC Client.", "cyan", "on_white")
        self.subscription = -1

        # Anchor IDL client
        self.provider = Provider(self.client, self.config.keypair) # Could be cause of programs
        self.idl = self.getIDL()
        self.program = Program(self.idl, self.config.program_id, self.provider)
        self.eventParser = EventParser(program_id = self.config.program_id, coder = self.program.coder)

        cprint("Initialized IDL.", "cyan", "on_white")

        # Error logging
        self.errors = open("errors.txt", "a")
    
        self.ws = None

        # Callbacks
        # May change this but for now dictionary where key is event name and value is callback
        # TODO: move to constructor.
        
        async def handleTransaction(notifier: TokenNotifier, events: list[Event], item: LogsNotification):
            for event in events:
                if event.name == "CreateEvent":
                    fstring = (f"Token Created: {event.data.name}\n" + 
                    f"\tSymbol: {event.data.symbol}\n" + f"\tMint: {event.data.mint}\n" + f"\tSignature: {item.result.value.signature}")
                    cprint(fstring, "white", "on_light_green")
                    break
                    
        self._callback = handleTransaction

    def setCallback(self, callback: Callable[['TokenNotifier', list[Event], LogsNotification], None]):
        
        """
        Sets the callback function to handle token events.

        Args:
            callback (Callable[['TokenNotifier', list[Event], LogsNotification], None]): 
                A function that processes events and logs notifications. It should accept 
                a TokenNotifier instance, a list of events, and a LogsNotification object.
        """

        self._callback = callback


    async def close(self):
        """
        Closes the websocket connection and cleanup resources
        """
        if self.ws is not None:
            await self.ws.close()


    async def processMessage(self, msg):
        """
        Process incoming message and handle token events.

        Args:
            msg: Incoming message containing transaction logs.

        This method iterates over the items in the message, parsing the logs
        of each transaction. If transaction logs contain events, it triggers the 
        callback function with the parsed events. In case of errors, logs the 
        error details including the transaction signature and the log line that
        caused the error.
        """

        last_tx_signature = ""
        last_line = ""

        try:
            for item in msg:
                if type(item) == LogsNotification:
                    # Array of events of said transaction

                    signature = item.result.value.signature
                    logs = item.result.value.logs

                    last_tx_signature = signature

                    events = []

                    for line in logs:

                        # sets last line for error handling. kinda scuffed
                        last_line = line

                        # For some reason there are certain lines that break the parser. this is to ignore them
                        if line.lower().startswith("program log: ") and len(line.lower().split("program log: ")[1]) < (10):
                            continue

                        log = self.eventParser.handle_program_log(line) # (Optional Event, Optional String, Bool)

                        if log[0] is not None:
                            events.append(log[0])
                    
                    if len(events) > 0:
                        asyncio.create_task(self._callback(self, events, item))
                    
        except Exception as e:
            logger.log(logging.ERROR, f"Error: {e}\nFor transaction: {last_tx_signature}\nLine: {last_line}\n\n")
            logger.log(logging.ERROR, traceback.format_exc())
            

    async def initWebsocket(self):
        """
        Initializes the websocket connection and subscribes to logs of messages containing the program id.
        
        Listens to incoming logs and calls the callback function with the parsed events.
        
        Automatically unsubscribes from logs and closes the client and websocket after 'run_time' seconds.
        
        If an error occurs during the process, logs the error to the error file.
        """
        async with connect(self.config.wss_url) as ws:
            try:
                self.ws = ws

                cprint("Subscribing to logs...", "white", "on_light_grey")

                # Subscribes to logs of messages containing the program id
                mention_filter = RpcTransactionLogsFilterMentions(self.config.program_id)
                await ws.logs_subscribe(mention_filter, commitment=self.config.commitment)

                # Gets the subscription id
                resp = await ws.recv()
                self.subscription = resp[0].result

                cprint(f"Subscribed to logs - {self.subscription}", "white", "on_light_grey")

                async def handle_messages():
                    async for msg in ws:
                        logger.log(logging.INFO, f"Recieved message from websocket: {msg}")
                        await self.processMessage(msg)

                # Start the message handling task
                message_task = asyncio.create_task(handle_messages())

                # Wait for x seconds seconds
                await asyncio.sleep(self.config.run_time)

                # Cancel the message handling task
                message_task.cancel()

                # Unsubscribe from logs
                await ws.logs_unsubscribe(self.subscription)

                # Close the client and websocket
                await self.client.close()
                await ws.close()

            except Exception as e:
                cprint(f"Error: {e}", 'white', 'on_red')


    def getIDL(self):
        """
        Temporary method to load the IDL from a file. This will eventually be replaced with a method to download the IDL from the blockchain.
        
        Returns:
            Idl: the loaded IDL
        """
        return Idl.from_json(json.dumps(json.load(open('assets/idl.json', 'r'))))  # Temporary: Will eventually get this from blockchain from program.
    
    def _getMainIDL(self):
        """
        Temporary method to load the IDL from a file. This will eventually be replaced with a method to download the IDL from the blockchain.
        
        Returns:
            Idl: the loaded IDL
        """
        return Idl.from_json(json.dumps(json.load(open('idl.json', 'r'))))  # Temporary: Will eventually get this from blockchain from program.


async def main():
    notifier = TokenNotifier()
    await notifier.initWebsocket() 
    
if __name__ == "__main__":
    asyncio.run(main())

