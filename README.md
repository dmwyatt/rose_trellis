**Project under development.**


Examples
--------

We always need to first instantiate a TrelloClient which handles communicating with
the Trello API and handles rate limiting and caching.

```python
from rosetrellis.trello_client import TrelloClient
tc = TrelloClient()
```

Now get a Board:

```python
from rosetrellis.models import Board
board = Board.get_s('some_board_id`, tc)
```
Few things to note about the code above:

1. We always pass in the `TrelloClient` we've already instantiated to methods that communicate
 with the Trello API.
2. You have to provide the id of the Trello object you want.  This can be the 24-character
 id, or the short id you see in various Trello urls.
3. We used the synchronous version of `Board.get` called `Board.get_s`.  As rosetrellis is 
 built on asyncio, and not everyone wants or needs to use coroutines in their own code,
 we provide these synchronous versions of all of rosetrellis coroutines.

Moving on, let's change some attributes of a board:

```python
board.name = "I'm The Board"
board.desc = "This is the One True Board.  Bow before It."
board.save_s()
```
