# pump.fun-tracker
Python module to track transactions and token creations on the pump.fun exchange.
This is a work in project and code may not be 100% complete as this was ported from another project.

for this to work you may need to download IDL file from pump.fun

Sample usage:

```python
async def transactionCallback(notifier: tn.TokenNotifier, events: list[tn.Event], item: tn.LogsNotification):
    for event in events:
        if event.name == "CreateEvent":
            try:

                logger.log(logging.INFO, f"Requesting data from ipfs: {event.data.uri}")
                
                # get links to socials...
                response = await ipfsHandler.fetch(event.data.uri)

                printCreateEvent(notifier, event, response, item)
            except Exception as e:
                logger.log(logging.ERROR, f"Error: {e}")
                logger.log(logging.ERROR, traceback.format_exc())

async def main():
    notifier = tn.TokenNotifier()
    global ipfsHandler
    ipfsHandler = ipfs.IPFSHandler()
    notifier.setCallback(transactionCallback)
    await notifier.initWebsocket()

if __name__ == "__main__":
    asyncio.run(main())
```
