"""Real filesystem/socket contracts for personal setup (no provider calls)."""
import contextlib
import importlib.util
import io
from pathlib import Path
import socket
import stat
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('local_dev', Path(__file__).resolve().parents[2] / 'scripts/local_dev.py')
local_dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local_dev)


class LocalSetupTests(unittest.TestCase):
    def test_installed_node_version_with_v_prefix_is_recognized(self):
        version = local_dev.command_version(['node', '--version'])
        self.assertIsNotNone(version)
        self.assertEqual(version.split('.')[0], '22')

    def test_new_keys_are_unique_private_and_never_printed(self):
        keys = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / '.env.example').write_text('SECRET_KEY=placeholder\nGAME_AGENT_PROVIDER=codex\n')
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertTrue(local_dev.configure(root))
                key = (root / '.env').read_text().splitlines()[0].split('=', 1)[1]
                self.assertEqual(len(key), 64)
                self.assertNotIn(key, output.getvalue())
                self.assertEqual(stat.S_IMODE((root / '.env').stat().st_mode), 0o600)
                keys.append(key)
        self.assertNotEqual(*keys)

    def test_existing_config_and_database_survive_reconfiguration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env.example').write_text('SECRET_KEY=placeholder\nGAME_AGENT_PROVIDER=codex\n')
            original = b'SECRET_KEY=existing-secret\nGAME_AGENT_PROVIDER=claude\n'
            (root / '.env').write_bytes(original)
            (root / 'database.sqlite').write_bytes(b'existing-data')
            self.assertFalse(local_dev.configure(root))
            self.assertEqual((root / '.env').read_bytes(), original)
            self.assertEqual((root / 'database.sqlite').read_bytes(), b'existing-data')

    def test_existing_env_symlink_is_not_followed_or_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env.example').write_text('SECRET_KEY=placeholder\n')
            (root / 'elsewhere').write_text('preserve')
            (root / '.env').symlink_to(root / 'elsewhere')
            self.assertFalse(local_dev.configure(root))
            self.assertEqual((root / 'elsewhere').read_text(), 'preserve')

    def test_occupied_port_is_rejected_and_listener_survives(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            port = listener.getsockname()[1]
            with self.assertRaisesRegex(ValueError, 'occupied'):
                local_dev.require_free_port(port)
            with socket.create_connection(('127.0.0.1', port), timeout=1):
                connection, _ = listener.accept()
                connection.close()


if __name__ == '__main__':
    unittest.main()
