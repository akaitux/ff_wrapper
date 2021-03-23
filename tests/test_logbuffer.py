from ff_wrapper import logbuffer
import pytest


@pytest.fixture
def logbuf(max_size=4):
    logbuf = logbuffer.LogBuffer(max_size)
    return logbuf


def logbuf_append_range(logbuf, num_from, num_to):
    for i in range(num_from, num_to):
        logbuf.append(i)


class TestLogBuffer:

    def test_append(self, logbuf):
        logbuf_append_range(logbuf, 1, 6)
        last_items, _ = logbuf.get_last_items(1)
        assert last_items[0] == 5, f"append failed, it's not last element (returned {last_items[0]})"

    def test_position(self, logbuf):
        logbuf_append_range(logbuf, 1, 6)
        _, position = logbuf.get_last_items(1)
        assert position == 5, f"Added 5 elements, but position != 5 ({position})"

    def test_get_last_items_n_more_than_max(self, logbuf):
        n = 10
        logbuf_append_range(logbuf, 1, 4)
        last_items, _ = logbuf.get_last_items(n)
        assert last_items == [1, 2, 3], f"Wrong last items ({last_items})"

    def test_get_last_items_n_more_than_max_overflow(self, logbuf):
        n = 10
        logbuf_append_range(logbuf, 1, 7)
        last_items, _ = logbuf.get_last_items(n)
        assert last_items == [3, 4, 5, 6], f"Wrong last items ({last_items})"

    def test_get_last_items_not_overflow_and_n_greater_than_items(self, logbuf):
        n = 10
        logbuf_append_range(logbuf, 1, 4)
        last_items, _ = logbuf.get_last_items(n)
        assert last_items == [1, 2, 3], f"Wrong last items ({last_items})"

    def test_get_last_items_not_overflow_and_n_less_than_items(self, logbuf):
        n = 2
        logbuf_append_range(logbuf, 1, 4)
        last_items, _ = logbuf.get_last_items(n)
        assert last_items == [2, 3], f"Wrong last items ({last_items})"

    def test_get_last_items_not_overflow_and_n_equals_items(self, logbuf):
        n = 4
        logbuf_append_range(logbuf, 1, 5)
        last_items, _ = logbuf.get_last_items(n)
        assert last_items == [1, 2, 3, 4], f"Wrong last items ({last_items})"

    def test_get_last_items_overflow_and_n_greater_than_items(self, logbuf):
        n = 10
        logbuf_append_range(logbuf, 1, 20)
        last_items, _ = logbuf.get_last_items(n)
        assert last_items == [16, 17, 18, 19], f"Wrong last items ({last_items})"

    def test_get_last_items_overflow_and_n_less_than_items(self, logbuf):
        n = 2
        logbuf_append_range(logbuf, 1, 20)
        last_items, _ = logbuf.get_last_items(n)
        assert last_items == [18, 19], f"Wrong last items ({last_items})"

    def test_get_last_items_overflow_and_n_equals_items(self, logbuf):
        n = 4
        logbuf_append_range(logbuf, 1, 20)
        last_items, _ = logbuf.get_last_items(n)
        assert last_items == [16, 17, 18, 19], f"Wrong last items ({last_items})"
