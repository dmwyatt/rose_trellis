import logging
import pprint


logger = logging.getLogger(__name__)

_cache = {}


def get(id_: str):
	return _cache.get(id_)


def set(obj):
	_cache[obj.id] = obj


def remove(id_: str):
	del _cache[id_]
