.. rosetrellis documentation master file, created by
   sphinx-quickstart on Sat May  9 12:04:56 2015.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Rosetrellis: A Trello API client for doing stuff
================================================

Release |version|.

:doc:`Installation <user/install>`.

Rosetrellis is a client library for the Trello API.  It presents Trello objects
as Python objects that you can modify and the save back to Trello.  It is built
on top of the Python standard library package
`asyncio <https://docs.python.org/3/library/asyncio.html>`_.

>>> tc = TrelloClient()
>>> card = Card.get_s('o3SKtC9v', tc)
>>> card.name
'a card name'
>>> card.name = 'The Card of Destiny'
>>> card.save_s()

Rosetrellis makes working with Trello objects almost as easy as working with Python
objects.

Contents:

.. toctree::
   :maxdepth: 2

   user/install
   user/getting-started
   user/asyncio-tutorial
   api/code



Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

