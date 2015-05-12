###############
Getting Started
###############




***************************************
Why the *'_s'* on all of these methods?
***************************************
Rosetrellis is built on top of asyncio and most of its methods are asyncio
coroutines.  This is great because is enables parallel communication with Trello.
See :doc:`asyncio-tutorial` for why this is useful.

However, it can also be irritating when you don't need asyncio in your own code because
you can't directly call coroutine functions and get anything useful out of them:

>>> models.Card.get('552ffb5a94f9d7f0783d5fd6', tc)
<generator object get at 0x7f70fd2c2af8>

You can't do anything with that generator.

Rosetrellis includes synchronous versions of all of its asynchrounous functions named
with as their asynchronous version with a ``_s`` appended:

>>> models.Card.get_s('552ffb5a94f9d7f0783d5fd6', tc)
<Card: name='The Card of Destiny', id='552ffb5a94f9d7f0783d5fd6'>

**********************************
These examples won't work for you!
**********************************
Since you can't modify and retrieve items from my Trello account, you'll have to
substitute your own ids and information in the below examples.

***************
First of all...
***************
For rate limiting and caching purposes, we always instantiate a TrelloClient first.

Assuming you've set :ref:`Environment variables <envvar>`:

>>> from rosetrellis.trello_client import TrelloClient
>>> tc = TrelloClient()

**********
Get a Card
**********
First import the :mod:`~rosetrellis.models` module:

>>> from rosetrellis import models

Now let's get a Card instance from Trello using the :meth:`rose_trellis.models.Card.get` classmethod.

>>> card = models.Card.get_s('o3SKtC9v', tc))
>>> card
<Card: name='The Card of Destiny', id='552ffb5a94f9d7f0783d5fd6'>

You'll note that we gave the Trello shortLink as our id parameter (found in the url when viewing a card
on the Trello website).  We could have also provided the actual id, ``552ffb5a94f9d7f0783d5fd6``.

*************
Modify a Card
*************
Let's change the card description:

>>> from rosetrellis.util import easy_run
>>> card.desc
'just a card'
>>> card.desc = 'The Card to End All Cards be here.'
>>> card.save_s()

We just PUT our new card description back to the Trello API.

.. _relations:

Card relations
--------------
We know other things about our card.  For example, we know it belongs to a list...

>>> card.list
<List: name='the list', id='552bf33fe7a8abc6ea057a38'>

When we got this card, ``rosetrellis`` automatically built the related
:class:`~rosetrellis.models.Lists` object.

We can modify this Lists object just like we can any other Trello object.

>>> cards.list.name = 'List of The Card of Destiny'
>>> cards.list.save_s()

We maintain just one instance of any object so that we maintain consistency.

To demonstrate, we'll get the list for this card:

>>> destiny_list = models.Lists.get_s(cards.list.id, tc)

We'll also get another card that's on the same list as our first card:

>>> other_card = models.Card.get_s('d0dqcEna', tc)

And now check to see if the objects are all the same object:

>>> id(card.list) == id(destiny_list) == id(other_card.list)
True

Check the name of the list:

>>> card.list.name
'the list'

See if it's the same for the other two references to it:

>>> destiny_list.name
'the list'
>>> other_card.list
'the list'

Change the name:

>>> card.list.name = 'MEGA LIST'

See if it changed on the other two references:

>>> destiny_list.name
'MEGA LIST'
>>> other_card.list.name
'MEGA LIST'

**************************
Getting more than one Card
**************************
Rosetrellis has the convenience method ``get_many`` on TrelloObject instances.

Provide it with a list of ids and it will retrieve them all asynchronously.

>>> card_ids = ['o3SKtC9v', '2eZy9NeR', '552bf38384f48e93d062f1f2']
>>> cards = Card.get_many_s(card_ids, tc)
>>> cards
[<Card: name='The Card of Destiny', id='552ffb5a94f9d7f0783d5fd6'>,
 <Card: name='cake', id='552bf362041f1b2d3207d08f'>,
 <Card: name='cat', id='552bf38384f48e93d062f1f2'>]

.. _recursive:

*************************************
Recursive building of related objects
*************************************
When you retrieve an object from the Trello API, it returns some JSON that looks
like this:

.. code-block:: json

   {
     "id": "4fc00640fd1b3557593b1972",
     "closed": false,
     "dateLastActivity": "2015-05-05T15:55:05.619Z",
     "desc": "",
     "descData": null,
     "due": null,
     "idBoard": "4fc005acfd1b3557593aeaf0",
     "idChecklists": [
       "55121944593d6f1dd9d79489"
     ],
     "idList": "4fc005acfd1b3557593aeaf1"
   }

As shown in :ref:`relations`, rosetrellis automatically builds the related objects
referenced by things like ``idList``, ``idChecklists``, and ``idBoard``.  When getting
many objects, this can cause *lots* of network requests.

If you're getting lots of things you can suppress this behavior by passing the
``inflate_children=False`` keyword argument to any of the methods that get one or
more objects.

See the next section :ref:`get_all` for an example.

.. _get_all:

*******************
Getting *all* cards
*******************
We can get *all* cards for an account by using the ``get_all`` method.

Notice how we pass ``inflate_children=False`` as talked about in :ref:`recursive`.

>>> all_cards = Card.get_all_s(tc, inflate_children=False)
>>> all_cards
[<Card: name='The Card of Destiny', id='552ffb5a94f9d7f0783d5fd6'>,
 <Card: name='cake', id='552bf362041f1b2d3207d08f'>,
 <Card: name='cat', id='552bf38384f48e93d062f1f2'>
 ...and many more...
]
