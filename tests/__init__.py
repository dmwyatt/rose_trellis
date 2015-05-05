import asyncio
from unittest.mock import Mock


def async_test(f):
	def wrapper(*args, **kwargs):
		coro = asyncio.coroutine(f)
		future = coro(*args, **kwargs)
		loop = asyncio.get_event_loop()
		loop.run_until_complete(future)

	return wrapper


def get_mock_coro(return_value):
	@asyncio.coroutine
	def mock_coro(*args, **kwargs):
		return return_value

	return Mock(wraps=mock_coro)
