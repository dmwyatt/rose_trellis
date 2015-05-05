import unittest
from rose_trellis.util import join_url


class TestUtil(unittest.TestCase):
	def test_join_url(self):
		url_base = 'https://api.trello.com/1/'
		expected = url_base + 'what'
		self.assertEqual(join_url('what'), expected)
		self.assertEqual(join_url('/what'), expected)
		self.assertEqual(join_url(''), url_base[:-1])
		self.assertEqual(join_url('what/'), expected)
		self.assertEqual(join_url('/what/'), expected)
