import unittest
from unittest.mock import Mock, patch

from rose_trellis import trello_client
from rose_trellis.TrelloObjects import Board
from rose_trellis.TrelloObjects.base import TrelloObjectCollection
from tests import async_test, get_mock_coro


class TestBoard(unittest.TestCase):
	def setUp(self):
		self.tc = Mock(trello_client)

	@async_test
	def test_get_all_boards(self):
		board1 = {'name': 'board1', 'id': 'id1'}
		board2 = {'name': 'board2', 'id': 'id2'}
		self.tc.get_boards = get_mock_coro([board1, board2])
		boards = yield from Board.get_all_boards(self.tc)

		# test that get_all_boards returns our two boards
		self.assertIn(Board(self.tc, obj_data=board1), boards)
		self.assertIn(Board(self.tc, obj_data=board2), boards)

		self.assertIsInstance(boards, TrelloObjectCollection)

	@patch.object(Board, 'state_from_api')
	@async_test
	def test_refresh(self, sfa_mock):
		board_data = {'name': 'a board', 'id': 'board_id'}
		self.tc.get_board = get_mock_coro(board_data)
		board = Board(self.tc, obj_id=board_data['id'])
		yield from board.refresh()

		# test that we fetch api data
		self.tc.get_board.assert_called_with(board_data['id'])

		# test that we apply api data to state
		sfa_mock.assert_called_with(board_data)
