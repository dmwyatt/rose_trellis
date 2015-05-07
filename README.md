Project under development.


Example
-------

```python
import asyncio

from rose_trellis import trello_client
from rose_trellis.models import Board

board_id = 'you should put the id of a board here'
event_loop = asyncio.get_event_loop()
tc = TrelloClient()

board = event_loop.run_until_complete(Board.get(board_id, tc))
```
