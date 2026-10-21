from itertools import count

import pytest

from app import storage


@pytest.fixture(autouse=True)
def reset_storage():
    storage.cards.clear()
    storage.card_ids = count(start=1)