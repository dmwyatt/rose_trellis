import abc
from urllib.parse import urljoin
import asyncio

from typing import Any, Callable, Sequence, List


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


def make_sequence_attrgetter(attr_name: str) -> Callable[Sequence[object]]:
	"""
	Get a callable which takes a sequence of objects and returns a list of
	``attr_name`` from each object in the sequence.

	:param attr_name: The name of the attribute to get from objects provided the the
		returned callable.
	:return: A callable which returns a list of attributes specified by ``attr_name``.
	"""

	def sequence_attrgetter(seq: Sequence[object]) -> List[object]:
		"""
		Returns a list of attributes from the provided sequence of objects.

		:param seq: The sequence to query.
		:return: List of attribute values.
		"""
		return [getattr(obj, attr_name, None) for obj in seq]

	return sequence_attrgetter


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

def get_child_obj_id(obj: object, obj_attr_name: str, obj_id_attr_name: str) -> str:
	"""
	:raises AttributeError: If don't have child object or child object does not have an id and object does not have obj_id_attr_name.
	"""
	if hasattr(obj, obj_attr_name):
		child_obj = getattr(obj, obj_attr_name, None)
		if hasattr(child_obj, 'id'):
			child_obj_id = getattr(child_obj, 'id', None)
			if child_obj_id:
				return child_obj_id

	return getattr(obj, obj_id_attr_name)
