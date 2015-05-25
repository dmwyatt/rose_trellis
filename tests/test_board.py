from unittest.mock import patch, Mock

from rosetrellis.models import Board
from tests import async_test, get_mock_coro
from tests.test_base import TestRoseTrellisBase

import rosetrellis.models


@patch('rosetrellis.base.obj_cache.get', lambda x: None)
class TestBoard(TestRoseTrellisBase):
	@async_test
	def test_get_data(self):
		get_ret_val = 'get ret val'
		self.tc.get_board = get_mock_coro(get_ret_val)

		an_id = 'an id'
		data = yield from Board._get_data(an_id, self.tc)

		self.tc.get_board.assert_called_with(an_id, fields="all")
		self.assertCountEqual(data, get_ret_val)

	@async_test
	def test_get_all(self):
		# I'll throw this test in anyway even though we're
		# just testing implementation details here.
		# There's not much else to test
		get_boards_ret_val = [1, 2, 3]
		self.tc.get_boards = get_mock_coro(get_boards_ret_val)
		get_many_ret_val = "you got many"
		Board.get_many = get_mock_coro(get_many_ret_val)
		all_boards = yield from Board.get_all(self.tc)

		self.assertEqual(all_boards, get_many_ret_val)
		self.tc.get_boards.assert_called_with(only_open=True)

	@async_test
	def test_delete_from_api(self):
		board = yield from Board.get({'id': 'id'}, self.tc)
		with self.assertRaises(NotImplementedError):
			yield from board._delete_from_api()

	@async_test
	def test_changes_to_api(self):
		update_ret_val = 'updated ret val'
		self.tc.update_board = get_mock_coro(update_ret_val)

		an_id = 'an id'
		board = yield from Board.get({'name': 'a board', 'id': an_id}, self.tc)

		changes = "bleh"
		updated_data = yield from board._changes_to_api(changes)
		self.assertEqual(updated_data, update_ret_val)

		self.tc.update_board.assert_called_with(an_id, changes)

	@async_test
	def test_get_api_update_from_state(self):
		an_id = 'an id'
		board = yield from Board.get({'name': 'a board', 'id': an_id}, self.tc)

		self.assertEqual({}, board._get_api_update_from_state())

		changes = {'name': 'new name'}
		board.name = changes['name']

		self.assertEqual(board._get_api_update_from_state(), changes)

		changes['closed'] = True
		board.closed = changes['closed']
		self.assertEqual(board._get_api_update_from_state(), changes)

		changes['desc'] = 'new desc'
		board.desc = changes['desc']
		self.assertEqual(board._get_api_update_from_state(), changes)

		changes['organization'] = 'new org'
		board.organization = changes['organization']
		self.assertEqual(board._get_api_update_from_state(), changes)

	@async_test
	def test_get_api_create_from_state_missing_required_fields(self):
		an_id = 'an id'
		board = yield from Board.get({'id': an_id}, self.tc)

		with self.assertRaises(ValueError):
			board._get_api_create_from_state()

	@async_test
	def test_get_api_create_from_state(self):
		an_id = 'an id'
		board_data = {'name': 'a board',
		              'desc': 'a description',
		              'powerUps': 'the awesome powerups',
		              'id': an_id}

		board = yield from Board.get(board_data, self.tc)

		create_data = board._get_api_create_from_state()
		expected_data = board_data.copy()
		del expected_data['id']

		self.assertEqual(expected_data, create_data)

	@async_test
	def test_get_labels(self):
		Label = Mock(rosetrellis.models.Label)
		Label.get_labels = get_mock_coro('some labels')
		an_id = 'an id'
		board = yield from Board.get({'name': 'a name', 'id': an_id}, self.tc)

		with patch('rosetrellis.models.Label', Label):
			labels = yield from board.get_labels()

		Label.get_labels.assert_called_with(an_id, self.tc)

	@async_test
	def test_get_lists(self):
		Lists = Mock(rosetrellis.models.Lists)
		Lists.get_many = get_mock_coro('buncha lists')

		board_lists = 'board lists'
		self.tc.get_board_lists = get_mock_coro(board_lists)

		an_id = 'an id'
		board = yield from Board.get({'name': 'a name', 'id': an_id}, self.tc)

		with patch('rosetrellis.models.Lists', Lists):
			lists = yield from board.get_lists()

		Lists.get_many.assert_called_with(board_lists, self.tc, inflate_children=True)

	@async_test
	def test_get_cards(self):
		Card = Mock(rosetrellis.models.Card)
		Card.get_many = get_mock_coro('buncha cards')

		board_cards = 'board cards'
		self.tc.get_board_cards = get_mock_coro(board_cards)

		an_id = 'an id'
		board = yield from Board.get({'name': 'a name', 'id': an_id}, self.tc)

		with patch('rosetrellis.models.Card', Card):
			cards = yield from board.get_cards()

		Card.get_many.assert_called_with(board_cards, self.tc, inflate_children=True)
		
	@async_test
	def test_get_checklists(self):
		Checklist = Mock(rosetrellis.models.Checklist)
		Checklist.get_many = get_mock_coro('buncha Checklists')

		board_checklists = 'board Checklists'
		self.tc.get_board_checklists = get_mock_coro(board_checklists)

		an_id = 'an id'
		board = yield from Board.get({'name': 'a name', 'id': an_id}, self.tc)

		with patch('rosetrellis.models.Checklist', Checklist):
			checklists = yield from board.get_checklists()

		Checklist.get_many.assert_called_with(board_checklists, self.tc, inflate_children=True)
