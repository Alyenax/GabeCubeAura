import termios
import unittest
from unittest.mock import patch
from signalbar.faceplate.transport import Link, LinkError


class DriverErrorTests(unittest.TestCase):
    def test_terminal_configuration_error_is_a_link_error_and_closes_fd(self):
        link=Link('/dev/test')
        with patch('signalbar.faceplate.transport.port_owner_details', return_value=[]), \
             patch('signalbar.faceplate.transport.os.open', return_value=42), \
             patch('signalbar.faceplate.transport.os.close') as close, \
             patch('signalbar.faceplate.transport.fcntl.flock'), \
             patch('signalbar.faceplate.transport.termios.tcgetattr', side_effect=termios.error(5,'USB disconnected')):
            with self.assertRaisesRegex(LinkError,'serial configuration failed'): link.open()
            close.assert_called_once_with(42)
            self.assertIsNone(link.fd)

    def test_terminal_drain_error_is_bounded_by_the_link_contract(self):
        link=Link('/dev/test'); link.fd=42
        with patch('signalbar.faceplate.transport.select.select',return_value=([],[42],[])), \
             patch('signalbar.faceplate.transport.os.write',return_value=3), \
             patch('signalbar.faceplate.transport.termios.tcdrain',side_effect=termios.error(5,'USB disconnected')):
            with self.assertRaisesRegex(LinkError,'serial drain failed'): link.write(b'abc')

    def test_vendor_retry_reset_error_is_not_an_uncaught_terminal_exception(self):
        link=Link('/dev/test',transport_profile='auto'); link.fd=42
        with patch.object(link,'_send_gif_once',side_effect=LinkError('baseline failed')), \
             patch('signalbar.faceplate.transport.termios.tcflush',side_effect=termios.error(5,'USB disconnected')):
            with self.assertRaisesRegex(LinkError,'serial reset failed'): link.send_gif(b'gif')
