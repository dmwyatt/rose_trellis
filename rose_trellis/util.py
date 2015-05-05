from urllib.parse import urljoin
import time


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


def rate_limited(max_per_second):
	min_interval = 1.0 / float(max_per_second)

	def decorate(func):
		last_time_called = [0.0]

		def rate_limited_function(*args, **kargs):
			elapsed = time.clock() - last_time_called[0]
			left_to_wait = min_interval - elapsed
			if left_to_wait > 0:
				time.sleep(left_to_wait)
			ret = func(*args, **kargs)
			last_time_called[0] = time.clock()
			return ret

		return rate_limited_function

	return decorate
