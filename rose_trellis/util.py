from urllib.parse import urljoin
import time
import asyncio
from typing import Any
from typing import Callable


TRELLO_URL_BASE = 'https://api.trello.com/1/'


def join_url(part: str) -> str:
	"""
	Adds `part` to  API base url.  Always returns url without trailing slash.

	:param part:
	:return: url
	"""
	part = part.strip('/')
	newpath = urljoin(TRELLO_URL_BASE, part)

	while newpath.endswith('/'):
		newpath = newpath[:-1]

	return newpath


def easy_run(gen) -> Any:
	el = asyncio.get_event_loop()
	return el.run_until_complete(gen)
