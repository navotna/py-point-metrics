import unittest
from unittest import mock

import metrics


class TestHandlerCleanup(unittest.TestCase):
    def test_handlers_closing(self):
        cursor = mock.MagicMock()
        cursor.__enter__.return_value = cursor
        connection = mock.MagicMock()
        connection.cursor.return_value = cursor

        metr_1 = metrics.get_metr("test_metr_1")
        metr_2 = metrics.get_metr("test_metr_2")
        handler = metrics.RDSHandler(connection)
        metr_1.add_handler(handler)
        metr_2.add_handler(handler)
        metrics.shutdown_handlers()

        connection.close.assert_called_once()


class TestMetrInheritance(unittest.TestCase):
    def test_metr_handlers_inheritance(self):
        handler = mock.MagicMock()
        metr_1 = metrics.get_metr("a")
        metr_1.add_handler(handler)
        metr_2 = metrics.get_metr("a.b")
        metr_2.rec(8)

        record = handler.handle.call_args_list[0][0][0]
        self.assertEqual(8, record.value)
        self.assertEqual("a.b", record.tag)


class TestMetr(unittest.TestCase):
    def test_int_record(self):
        handler = mock.MagicMock()
        metr = metrics.get_metr("test_int_record")
        metr.add_handler(handler)
        metr.rec(7)

        record = handler.handle.call_args_list[0][0][0]
        self.assertEqual(7, record.value)

    def test_counter_record_context(self):
        handler = mock.MagicMock()
        metr = metrics.get_metr("test_counter_record_context")
        metr.add_handler(handler)

        with metr.rec_counter() as counter:
            counter.add(2)
            counter.add(3)

        record = handler.handle.call_args_list[0][0][0]
        self.assertEqual(5, record.value)

    def test_counter_record(self):
        handler = mock.MagicMock()
        metr = metrics.get_metr("test_counter_record")
        metr.add_handler(handler)

        counter = metr.rec_counter()
        counter.add(8)
        counter.add(7)
        counter.close()

        record = handler.handle.call_args_list[0][0][0]
        self.assertEqual(15, record.value)

    def test_exception_record(self):
        handler = mock.MagicMock()
        metr = metrics.get_metr("test_exception_record")
        metr.add_handler(handler)

        @metr.rec_exception(ValueError)
        def f():
            raise ValueError

        try:
            f()
        except ValueError:
            record = handler.handle.call_args_list[0][0][0]
            self.assertEqual(1, record.value)
        else:
            self.fail()