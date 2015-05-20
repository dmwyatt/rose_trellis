import unittest
from unittest.mock import Mock, patch
from rosetrellis import trello_client
from rosetrellis.models import TrelloObject


class TestTrelloObject(unittest.TestCase):
	def setUp(self):
		# Make it so we can instantiate the abstract base class TrelloObject
		class ConcretedTrelloObject(TrelloObject):
			pass

		ConcretedTrelloObject.__abstractmethods__ = set()

		self.CTO = ConcretedTrelloObject
		self.tc = Mock(trello_client)

