Project under development.


Examples
-------

Let's get a Board instance...

```python
import asyncio

from rose_trellis import trello_client
from rose_trellis.models import Board

board_id = 'you should put the id of a board here'
event_loop = asyncio.get_event_loop()
tc = TrelloClient()

board = event_loop.run_until_complete(Board.get(board_id, tc))
```

Change some attributes of a board:

```python
board.name = "I'm The Board"
board.desc = "This is the One True Board.  Bow before It."
event_loop.run_until_complete(board.save())
```

Since rose_trellis is built on `asyncio` we can get a bunch of instances in parallel:

```python
board_ids = ["id_1", "id_2", "id_3", ...]
getters = [Board.get(board_id, tc) for board_id in board_ids]
boards = event_loop.run_until_complete(asyncio.gather(*getters))
```

We've got a helper method for that.

```python
event_loop.run_until_complete(Board.get_many(board_ids, tc))
```

If you're not going to use asyncio in your project, you can run all of our methods and 
functions with our helper function:

```python
from rose_trellis.util import easy_run

boards = easy_run(Board.get_many(board_ids, tc))
```
