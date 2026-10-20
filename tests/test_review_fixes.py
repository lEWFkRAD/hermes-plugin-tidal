import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load_plugin(home, name):
    constants = types.ModuleType("hermes_constants")
    constants.get_hermes_home = lambda: home
    registry = types.ModuleType("tools.registry")
    registry.tool_result = json.dumps
    registry.tool_error = lambda message: json.dumps({"error": message})
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    for key in list(sys.modules):
        if key == name or key.startswith(name + "."):
            del sys.modules[key]
    sys.modules[name] = module
    with patch.dict(sys.modules, {"hermes_constants": constants, "tools.registry": registry}):
        spec.loader.exec_module(module)
        loaded = {k: v for k, v in sys.modules.items() if k.startswith(name + ".")}
    sys.modules.update(loaded)
    return module


class TidalReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.plugin = load_plugin(self.home / "alpha", "review_tidal")
        self.auth = sys.modules["review_tidal.tidal_auth"]
        self.player = sys.modules["review_tidal.tidal_player"]

    def test_profile_switch_in_one_process_does_not_reuse_login_or_player(self):
        active = self.home / "alpha"
        with patch.object(self.auth, "get_hermes_home", side_effect=lambda: active), \
             patch.object(self.player, "get_hermes_home", side_effect=lambda: active):
            self.auth._save_session(Mock(save_session_to_file=lambda p: p.write_text("alpha")))
            self.player._write_state({"title": "alpha", "pid": 123})
            first_socket = self.player._sock_path()
            active = self.home / "beta"
            self.assertIsNone(self.auth.load_session())
            self.assertEqual(self.player._read_state(), {})
            self.assertNotEqual(self.player._sock_path(), first_socket)
            self.player._write_state({"title": "beta"})
            active = self.home / "alpha"
            self.assertEqual(self.player._read_state()["title"], "alpha")

    def test_registered_tools_expose_arguments_and_dispatch(self):
        ctx = Mock()
        self.plugin.register(ctx)
        self.assertEqual(ctx.register_tool.call_count, 5)
        for call in ctx.register_tool.call_args_list:
            registration = call.kwargs
            schema = registration["schema"]["parameters"]
            self.assertIn("action", schema["required"])
            self.assertTrue(schema["properties"]["action"]["enum"])
        tools = sys.modules["review_tidal.tidal_tools"]
        with patch.object(tools, "_session", return_value=Mock()), \
             patch.object(tools.tidal_player, "get_state", return_value={"playing": False}):
            result = json.loads(tools._handle_tidal_playback({"action": "get_state"}))
        self.assertNotIn("error", result)

    def test_profiles_have_separate_login_state_and_socket(self):
        other = load_plugin(self.home / "beta", "review_tidal_beta")
        auth2 = sys.modules["review_tidal_beta.tidal_auth"]
        player2 = sys.modules["review_tidal_beta.tidal_player"]
        self.auth._save_session(Mock(save_session_to_file=lambda p: p.write_text("alpha")))
        with patch.object(auth2, "_new_session") as session:
            self.assertIsNone(auth2.load_session())
            session.assert_not_called()
        self.assertEqual(self.auth._session_dir(), self.home / "alpha/plugin-data/tidal")
        self.assertEqual(self.player._state_dir(), self.auth._session_dir())
        self.assertNotEqual(self.player._sock_path(), player2._sock_path())

    @unittest.skipUnless(os.name == "posix", "POSIX mode bits; Windows uses directory ACL")
    def test_tokens_private_before_and_after_writer(self):
        observed = []
        def save(path):
            observed.append(stat.S_IMODE(path.stat().st_mode))
            path.write_text("synthetic-token")
        session = Mock(save_session_to_file=save)
        self.auth._save_session(session)
        os.chmod(self.auth._session_file(), 0o644)
        self.auth._save_session(session)
        self.assertEqual(observed, [0o600, 0o600])
        self.assertEqual(stat.S_IMODE(self.auth._session_file().stat().st_mode), 0o600)

    def test_interactive_login_keeps_pending_state_off_disk(self):
        session = Mock()
        session.pkce_login_url.return_value = "https://example.invalid/login"
        session.save_session_to_file.side_effect = lambda p: p.write_text("synthetic-token")
        with patch.object(self.auth, "_new_session", return_value=session), \
             patch.object(sys, "stdin", Mock(isatty=lambda: True)), \
             patch("builtins.input", return_value="https://example.invalid/callback?code=synthetic"):
            self.assertTrue(self.auth.device_login(printer=lambda s: None))
        self.assertTrue(self.auth._session_file().exists())
        self.assertFalse((self.auth._session_dir() / "pending.json").exists())

    def test_noninteractive_login_fails_without_starting_auth(self):
        with patch.object(sys, "stdin", Mock(isatty=lambda: False)), \
             patch.object(self.auth, "_new_session") as session:
            self.assertFalse(self.auth.device_login(printer=lambda s: None))
            session.assert_not_called()
        self.assertFalse(self.auth._session_dir().exists())

    def test_logout_removes_profile_credentials(self):
        self.auth._session_dir().mkdir(parents=True)
        self.auth._session_file().write_text("synthetic")
        (self.auth._session_dir() / "pending.json").write_text("synthetic")
        self.auth.logout()
        self.assertFalse(self.auth._session_file().exists())
        self.assertFalse((self.auth._session_dir() / "pending.json").exists())

    def test_mpv_option_like_url_is_positional(self):
        with patch.object(self.player, "stop"), patch.object(self.player, "_mpv_bin", return_value="mpv"), \
             patch.object(self.player, "_write_state"), patch.object(self.player.time, "sleep"), \
             patch.object(self.player.subprocess, "Popen") as popen:
            popen.return_value.pid = 123
            self.player.play_url("--script=synthetic.lua")
        argv = popen.call_args.args[0]
        self.assertEqual(argv[-2:], ["--", "--script=synthetic.lua"])
        self.assertFalse(popen.call_args.kwargs.get("shell", False))

    @unittest.skipUnless(os.name == "posix", "POSIX mode bits")
    def test_refresh_protects_existing_credential_file(self):
        self.auth._session_dir().mkdir(parents=True)
        self.auth._session_file().write_text("synthetic")
        self.auth._session_file().chmod(0o644)
        def login(path):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            return True
        session = Mock(login_session_file=login)
        with patch.object(self.auth, "_new_session", return_value=session):
            self.assertIs(self.auth.load_session(), session)


if __name__ == "__main__":
    unittest.main()
