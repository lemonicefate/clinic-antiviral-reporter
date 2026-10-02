import unittest

from service.settings import Settings, SettingsError


class SettingsTest(unittest.TestCase):
    def environment(self):
        return {
            "CLINIC_REPORTER_STATE_DIR": r"C:\ClinicReporter",
            "CLINIC_REPORTER_HIS_SOURCE_PATH": r"\\his\Data\source",
            "CLINIC_REPORTER_BACKUP_ROOT": r"\\his\ReporterBackup\central",
        }

    def test_backup_must_use_a_different_share_even_on_another_server(self):
        for backup in (r"\\his\DATA\backups", r"\\other\data\backups\\"):
            with self.subTest(backup=backup), self.assertRaises(SettingsError):
                Settings.from_environment({
                    "CLINIC_REPORTER_STATE_DIR": r"C:\ClinicReporter",
                    "CLINIC_REPORTER_HIS_SOURCE_PATH": r"\\his\Data\source",
                    "CLINIC_REPORTER_BACKUP_ROOT": backup,
                })

    def test_only_local_absolute_state_and_plain_unc_sources_are_accepted(self):
        invalid = {
            "CLINIC_REPORTER_STATE_DIR": ["relative", "C:relative", r"\\his\state", r"C:\state\..\data"],
            "CLINIC_REPORTER_HIS_SOURCE_PATH": [r"C:\data", r"\\?\C:\data", r"\\his\data\..\other"],
            "CLINIC_REPORTER_BACKUP_ROOT": ["relative", r"\\.\device\backup", r"\\his\backup\file:stream"],
        }
        for name, values in invalid.items():
            for value in values:
                with self.subTest(name=name, value=value):
                    with self.assertRaises(SettingsError) as caught:
                        Settings.from_environment(self.environment() | {name: value})
                    self.assertNotIn(value, str(caught.exception))
        valid = Settings.from_environment(self.environment())
        self.assertEqual(str(valid.backup_root), r"\\his\ReporterBackup\central")

    def test_safe_defaults_and_strict_operational_values(self):
        settings = Settings.from_environment(self.environment())
        self.assertFalse(settings.export_enabled)
        self.assertEqual(settings.scan_interval_seconds, 60)
        self.assertEqual(settings.backup_interval_seconds, 1800)
        self.assertEqual(settings.bind_host, "127.0.0.1")
        for key, value in (
            ("EXPORT_ENABLED", "yes"), ("ENV", "prod"),
            ("HIS_SCAN_INTERVAL_SECONDS", "0"), ("BACKUP_INTERVAL_SECONDS", "3601"),
            ("BIND_PORT", "65536"), ("BIND_HOST", "0.0.0.0"),
        ):
            with self.subTest(key=key), self.assertRaises(SettingsError):
                Settings.from_environment(self.environment() | {"CLINIC_REPORTER_" + key: value})

    def test_production_rejects_placeholder_and_documentation_addresses(self):
        env = self.environment() | {"CLINIC_REPORTER_ENV": "production"}
        for key, value in (
            ("HIS_SOURCE_PATH", r"\\192.0.2.199\Data"),
            ("BACKUP_ROOT", r"\\his\REPLACE_WITH_BACKUP"),
            ("BACKUP_ROOT", r"\\localhost\backup"),
            ("BACKUP_ROOT", r"\\127.0.0.1\backup"),
            ("HIS_SOURCE_PATH", r"\\example.com\Data"),
            ("BIND_HOST", "198.51.100.10"),
        ):
            with self.subTest(key=key), self.assertRaises(SettingsError):
                Settings.from_environment(env | {"CLINIC_REPORTER_" + key: value})
        self.assertEqual(Settings.from_environment(env).environment, "production")
