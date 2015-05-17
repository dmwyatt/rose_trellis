import abc
from urllib.parse import urljoin
import asyncio

from typing import Any


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


class _Synchronizer(abc.ABCMeta):
	"""
	This metaclass functions as a replacement for abc.ABCMeta that adds a synchronous
	version of every asynchronous method in	the class.

	Finds every coroutine method by checking every method with
	:func:`asyncio.iscoroutinefunction`.  It then creates a synchronous version with
	'_s' appended to the method name.
	"""

	def __new__(cls, clsname, bases, dct):
		new_dct = {}
		for name, val in dct.items():
			# Make a sync version of all coroutine functions
			if asyncio.iscoroutinefunction(val):
				meth = cls.sync_maker(name)
				syncname = '{}_s'.format(name)
				meth.__name__ = syncname
				meth.__qualname__ = '{}.{}'.format(clsname, syncname)
				new_dct[syncname] = meth
			elif isinstance(val, classmethod) and asyncio.iscoroutinefunction(val.__func__):
				meth = cls.sync_maker(val.__func__.__name__)
				syncname = '{}_s'.format(name)
				meth.__name__ = syncname
				meth.__qualname__ = '{}.{}'.format(clsname, syncname)
				new_dct[syncname] = classmethod(meth)

		dct.update(new_dct)
		return super().__new__(cls, clsname, bases, dct)

	@staticmethod
	def sync_maker(func):
		def sync_func(self, *args, **kwargs):
			meth = getattr(self, func)
			return asyncio.get_event_loop().run_until_complete(meth(*args, **kwargs))

		return sync_func


class Synchronizer(metaclass=_Synchronizer):
	pass

def is_valid_website(website: str) -> bool:
		return website.startswith('http://') or website.startswith('https://')
