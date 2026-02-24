import os
import tempfile
import unittest

import app as appmod


class TestAppSetupHelpers(unittest.TestCase):
    def setUp(self):
        self.old_config_env_file = appmod.CONFIG_ENV_FILE
        self.old_basic_user = appmod.BASIC_USER
        self.old_basic_pass = appmod.BASIC_PASS
        self.old_env_user = os.environ.get("BASIC_AUTH_USER")
        self.old_env_pass = os.environ.get("BASIC_AUTH_PASS")

    def tearDown(self):
        appmod.CONFIG_ENV_FILE = self.old_config_env_file
        appmod.BASIC_USER = self.old_basic_user
        appmod.BASIC_PASS = self.old_basic_pass

        if self.old_env_user is None:
            os.environ.pop("BASIC_AUTH_USER", None)
        else:
            os.environ["BASIC_AUTH_USER"] = self.old_env_user

        if self.old_env_pass is None:
            os.environ.pop("BASIC_AUTH_PASS", None)
        else:
            os.environ["BASIC_AUTH_PASS"] = self.old_env_pass

    def test_validate_setup_credentials(self):
        self.assertIsNotNone(appmod._validate_setup_credentials("", "12345678", "12345678"))
        self.assertIsNotNone(appmod._validate_setup_credentials("user", "12345678", "12345679"))
        self.assertIsNotNone(appmod._validate_setup_credentials("ad", "12345678", "12345678"))
        self.assertIsNotNone(appmod._validate_setup_credentials("admin", "123", "123"))
        self.assertIsNotNone(
            appmod._validate_setup_credentials(
                appmod.DEFAULT_BASIC_USER, appmod.DEFAULT_BASIC_PASS, appmod.DEFAULT_BASIC_PASS
            )
        )
        self.assertIsNone(appmod._validate_setup_credentials("admin_new", "StrongPwd_123", "StrongPwd_123"))

    def test_save_env_values_and_set_admin_credentials(self):
        with tempfile.TemporaryDirectory() as td:
            appmod.CONFIG_ENV_FILE = os.path.join(td, "config.env")
            with open(appmod.CONFIG_ENV_FILE, "w", encoding="utf-8") as f:
                f.write("# test config\nBASIC_AUTH_USER=old_user\nOTHER_KEY=1\n")

            appmod._save_env_values({"BASIC_AUTH_USER": "new_user", "BASIC_AUTH_PASS": "new_pass"})
            with open(appmod.CONFIG_ENV_FILE, "r", encoding="utf-8") as f:
                text = f.read()

            self.assertIn("BASIC_AUTH_USER=new_user", text)
            self.assertIn("BASIC_AUTH_PASS=new_pass", text)
            self.assertIn("OTHER_KEY=1", text)

            appmod._set_admin_credentials(appmod.DEFAULT_BASIC_USER, appmod.DEFAULT_BASIC_PASS)
            self.assertTrue(appmod._is_initial_setup_required())

            appmod._set_admin_credentials("new_user", "new_pass")
            self.assertFalse(appmod._is_initial_setup_required())


if __name__ == "__main__":
    unittest.main()
