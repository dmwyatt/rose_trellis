import unittest
from unittest.mock import Mock, patch

from rosetrellis import trello_client
from rosetrellis.TrelloObjects import Checklist, Card
from rosetrellis.TrelloObjects.base import TrelloObjectCollection
from rosetrellis.TrelloObjects.models import CheckItem
from tests import async_test, get_mock_coro


checklist_data = {
	"id": "550b452ebfe4c11e98689ba4",
	"name": "Repairs",
	"idBoard": "4fc005acfd1b3557593aeaf0",
	"idCard": "4fc00744b067f2f339eab2da",
	"pos": 16384,
	"checkItems": [
		{
			"state": "incomplete",
			"id": "550b45392adae27add63d280",
			"name": "Fix siding!",
			"nameData": None,
			"pos": 17076
		},
		{
			"state": "incomplete",
			"id": "550b45392blah27wut63d280",
			"name": "leaking roof",
			"nameData": None,
			"pos": 17076
		}
	]
}


class TestChecklist(unittest.TestCase):

	def setUp(self):
		self.tc = Mock(trello_client)

	@async_test
	def test_refresh(self):
		id_ = 'nope'
		with patch.object(Checklist, 'state_from_api', return_value=None) as mocked_method:
			value = "a return value"
			self.tc.get_checklist = get_mock_coro(value)
			cl = Checklist(self.tc, obj_id=id_)
			yield from cl.refresh()

			# test that we fetch api data
			self.tc.get_checklist.assert_called_with(id_)

			# test that we apply api data to state
			mocked_method.assert_called_with(value)

	@async_test
	def test_delete(self):
		self.tc.delete_checklist = get_mock_coro(None)
		cl = Checklist(self.tc, obj_id='nope')
		yield from cl.delete()

		# test that we call the method to delete via the api
		self.tc.delete_checklist.assert_called_with('nope')


	@patch.object(Checklist, 'state_from_api')
	@patch.object(Checklist, 'get_api_from_state')
	@async_test
	def test_save_with_changes(self, gafs_mock, sfa_mock):
		changes = {'one': 1}
		gafs_mock.return_value = changes
		sfa_mock.return_value = None
		id_ = 'nope'

		new_state_fake = "fakefakefake!"
		self.tc.update_checklist = get_mock_coro(new_state_fake)

		cl = Checklist(self.tc, obj_id=id_)
		cl.checkItems = Mock()
		cl.checkItems.save = get_mock_coro(None)

		yield from cl.save()

		# test that we call the method to update api with our changes
		self.tc.update_checklist.assert_called_with(id_, changes)

		# test that we update our state with the new api data
		sfa_mock.assert_called_with(new_state_fake)

		# just a little test to make sure we properly mocked the
		# method to transform current state to changes to apply to api
		self.assertEqual(gafs_mock.call_count, 1)

	@patch.object(Checklist, 'state_from_api')
	@patch.object(Checklist, 'get_api_from_state')
	@async_test
	def test_save_without_changes(self, gafs_mock, sfa_mock):
		id_ = 'nope'
		gafs_mock.return_value = None

		self.tc.update_checklist = get_mock_coro(None)

		cl = Checklist(self.tc, obj_id=id_)
		cl.checkItems = Mock()
		cl.checkItems.save = get_mock_coro(None)

		yield from cl.save()

		# test that we didn't try to update the api since there
		# are no changes
		self.assertEqual(self.tc.update_checklist.call_count, 0)

		# test to make sure we tried to get changes to send to api
		self.assertEqual(gafs_mock.call_count, 1)

		# test that we didn't try to update our own state with
		# new api data since we didn't have any changes to send
		# to the api
		self.assertEqual(sfa_mock.call_count, 0)

	def test_state_from_api(self):
		cl = Checklist(self.tc, obj_data=checklist_data)

		# Test that all our keys got set on the Checklist obj
		for key in checklist_data:
			self.assertTrue(hasattr(cl, key), "Checklist does not have attr: {}".format(key))

		# Test that our CheckItem objects were instantiated
		for ci in cl.checkItems:
			self.assertIsInstance(ci, CheckItem, "Not all items in cl.checkItems is a CheckItem")

		# Test that we're using a TrelloObjectCollection
		self.assertIsInstance(cl.checkItems, TrelloObjectCollection)

	def test_change_card(self):
		cl = Checklist(self.tc, obj_data=checklist_data)

		# Test that we don't have any changes right after instantiation of obj
		self.assertFalse(cl.get_api_update_from_state())

		new_card_id = 'new_card_id'
		new_card = Card(self.tc, obj_id=new_card_id)
		cl.card = new_card

		# Test that we provide the right api data for a changed card
		self.assertEqual(cl.get_api_update_from_state().get('idCard'), new_card_id)

	def test_change_misc(self):
		cl = Checklist(self.tc, obj_data=checklist_data)

		# Test that we don't have any changes right after instantiation of obj
		self.assertFalse(cl.get_api_update_from_state())

		new_name = 'new name'
		cl.name = new_name

		new_pos = 'top'
		cl.pos = new_pos

		# test that we provide the right api data for a changed name and position
		self.assertEqual(cl.get_api_update_from_state().get('name'), new_name)
		self.assertEqual(cl.get_api_update_from_state().get('pos'), new_pos)



class TestChecklistItem(unittest.TestCase):
	def setUp(self):
		self.data = {
			"state": "incomplete",
			"id": "550b45392adae27add63d280",
			"name": "Pick up trash everywhere!",
			"nameData": None,
			"pos": 17076
		}


