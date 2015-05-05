import unittest
from unittest.mock import Mock, patch
from rose_trellis import trello_client
from rose_trellis.TrelloObjects.base import TrelloObject


class TestTrelloObject(unittest.TestCase):
	def setUp(self):
		# Make it so we can instantiate the abstract base class TrelloObject
		class ConcretedTrelloObject(TrelloObject):
			pass

		ConcretedTrelloObject.__abstractmethods__ = set()

		self.CTO = ConcretedTrelloObject
		self.tc = Mock(trello_client)

	def test_init_with_id(self):
		obj_id = 'objid'
		trello_object = self.CTO(self.tc, obj_id=obj_id)
		self.assertEqual(trello_object.id, obj_id)

	def test_init_with_obj_data(self):
		obj_data = {'key1': 1, 'key2': 2}
		with patch.object(self.CTO, 'state_from_api', return_value=None) as mocked_method:
			trello_object = self.CTO(self.tc, obj_data=obj_data)
			mocked_method.assert_called_with(obj_data)

	def test_init_with_invalid_options(self):
		with self.assertRaises(ValueError):
			self.CTO(self.tc)

	def test_valid_id_in_data(self):
		with patch.object(self.CTO, 'validate_id', return_value=True) as mocked_method:
			trello_object = self.CTO(self.tc, obj_id='an id')
			self.assertFalse(trello_object.valid_id_in_data({'no_id': 'here'}))
			self.assertTrue(trello_object.valid_id_in_data({'id': 'here'}))
			mocked_method.assert_called_with('here')

	def test_validate_id(self):
		trello_object = self.CTO(self.tc, obj_id="an id")
		self.assertFalse(trello_object.validate_id('not an id'))
		self.assertTrue(trello_object.validate_id('550b452ebfe4c11e98689ba4'))

	def test_generic_state_from_api(self):
		trello_object = self.CTO(self.tc, obj_id='an id')
		api_data = {'key1': 1, 'key2': 2, 'id': '550b452ebfe4c11e98689ba4'}
		trello_object.generic_state_from_api(api_data)
		self.assertEqual(api_data['key1'], trello_object.key1)
		self.assertEqual(api_data['key2'], trello_object.key2)
		self.assertEqual(api_data['id'], trello_object.id)

	def test_field_has_changed(self):
		trello_object = self.CTO(self.tc, obj_id='an id')
		api_data = {'key1': 1, 'key2': 2, 'id': '550b452ebfe4c11e98689ba4'}
		trello_object.generic_state_from_api(api_data)

		trello_object.id = 'new id'

		self.assertTrue(trello_object.field_has_changed('id'))

		trello_object.id = api_data['id']

		self.assertFalse(trello_object.field_has_changed('id'))
