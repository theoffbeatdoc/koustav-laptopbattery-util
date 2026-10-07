import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kbu.battery import PowerSample, PowerState, classify  # noqa: E402
from kbu.config import Config, parse_config  # noqa: E402
from kbu.constants import Action, parse_action_uri  # noqa: E402
from kbu.engine import AlertEngine, ClearToast, Kind, ShowToast  # noqa: E402

CH, AC, DIS = PowerState.CHARGING, PowerState.AC_NOT_CHARGING, PowerState.DISCHARGING


def S(state, pct):
    return PowerSample(state, pct, state is not DIS)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.e = AlertEngine(Config(), clock=self.clock)

    def shows(self, effects):
        return [x for x in effects if isinstance(x, ShowToast)]

    def test_A_start_above_threshold_notifies_once(self):
        self.assertEqual(len(self.shows(self.e.tick(S(CH, 85)))), 1)
        for _ in range(20):
            self.assertEqual(self.e.tick(S(CH, 85)), [])

    def test_B_fluctuation_no_repeat(self):
        out = []
        for p in (79, 80, 79, 80, 81):
            out += self.shows(self.e.tick(S(CH, p)))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].percent, 80)

    def test_C_D_unplug_replug_is_new_cycle(self):
        self.assertEqual(len(self.shows(self.e.tick(S(CH, 85)))), 1)
        eff = self.e.tick(S(DIS, 85))
        self.assertIn(ClearToast(Kind.UPPER), eff)
        self.assertEqual(len(self.shows(self.e.tick(S(CH, 85)))), 1)

    def test_E_charge99_is_temporary_and_fires_at_99(self):
        self.e.tick(S(CH, 80))
        self.assertTrue(self.e.handle_action(Action.CHARGE_99))
        self.assertEqual(self.e.effective_upper_target, 99)
        self.assertEqual(self.e.tick(S(CH, 85)), [])
        self.assertEqual(self.e.tick(S(CH, 98)), [])
        out = self.shows(self.e.tick(S(CH, 99)))
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].final)
        self.assertEqual(self.e.tick(S(CH, 99)), [])
        # config untouched, override reset on unplug
        self.e.tick(S(DIS, 99))
        self.assertEqual(self.e.effective_upper_target, 80)

    def test_charge99_when_already_at_99(self):
        self.e.tick(S(CH, 99))
        self.assertTrue(self.e.handle_action(Action.CHARGE_99))
        self.assertEqual(len(self.shows(self.e.tick(S(CH, 99)))), 1)

    def test_F_ignore_suppresses_until_cycle_end(self):
        self.e.tick(S(CH, 80))
        self.assertTrue(self.e.handle_action(Action.IGNORE_UPPER))
        for p in (81, 90, 99):
            self.assertEqual(self.e.tick(S(CH, p)), [])
        self.e.tick(S(DIS, 99))
        self.assertEqual(len(self.shows(self.e.tick(S(CH, 90)))), 1)

    def test_G_renotify_single_timer_and_reevaluation(self):
        self.e.tick(S(CH, 82))
        self.e.handle_action(Action.RENOTIFY_UPPER)
        self.clock.t += 200
        self.e.handle_action(Action.RENOTIFY_UPPER)  # replaces, not stacks
        self.assertEqual(self.e.next_deadline(), self.clock.t + 300)
        self.clock.t += 299
        self.assertEqual(self.e.tick(S(CH, 83)), [])
        self.clock.t += 2
        self.assertEqual(len(self.shows(self.e.tick(S(CH, 84)))), 1)
        self.assertIsNone(self.e.next_deadline())

    def test_renotify_dropped_if_unplugged(self):
        self.e.tick(S(CH, 82))
        self.e.handle_action(Action.RENOTIFY_UPPER)
        self.clock.t += 301
        eff = self.e.tick(S(DIS, 82))
        self.assertEqual(self.shows(eff), [])
        self.assertIsNone(self.e.next_deadline())

    def test_renotify_still_fires_when_plugged_but_not_charging(self):
        self.e.tick(S(CH, 90))
        self.e.handle_action(Action.RENOTIFY_UPPER)
        self.clock.t += 301
        self.assertEqual(len(self.shows(self.e.tick(S(AC, 95)))), 1)

    def test_H_disabled_no_notifications(self):
        self.e.update_config(Config(enabled=False))
        self.assertEqual(self.e.tick(S(CH, 95)), [])
        self.assertEqual(self.e.tick(S(DIS, 5)), [])
        self.e.update_config(Config(enabled=True))
        self.assertEqual(len(self.shows(self.e.tick(S(CH, 95)))), 1)

    def test_ac_not_charging_does_not_trigger_or_reset(self):
        self.assertEqual(self.e.tick(S(AC, 90)), [])         # OEM hold: silent
        self.e.tick(S(CH, 90))
        self.assertEqual(self.e.tick(S(AC, 90)), [])
        self.assertEqual(self.e.tick(S(CH, 90)), [])         # same cycle: no repeat

    def test_lower_flow(self):
        self.assertEqual(self.e.tick(S(DIS, 21)), [])
        out = self.shows(self.e.tick(S(DIS, 20)))
        self.assertEqual((out[0].kind, out[0].percent), (Kind.LOWER, 20))
        self.assertEqual(self.e.tick(S(DIS, 19)), [])
        self.e.handle_action(Action.RENOTIFY_LOWER)
        self.clock.t += 301
        self.assertEqual(len(self.shows(self.e.tick(S(DIS, 18)))), 1)
        self.e.handle_action(Action.IGNORE_LOWER)
        self.assertEqual(self.e.tick(S(DIS, 10)), [])
        self.e.tick(S(CH, 10))                               # plug in = cycle end
        self.assertEqual(len(self.shows(self.e.tick(S(DIS, 15)))), 1)

    def test_stale_actions_rejected(self):
        self.assertFalse(self.e.handle_action(Action.CHARGE_99))
        self.e.tick(S(CH, 80))
        self.e.tick(S(DIS, 80))
        self.assertFalse(self.e.handle_action(Action.IGNORE_UPPER))
        self.assertFalse(self.e.handle_action(Action.RENOTIFY_UPPER))

    def test_unknown_and_no_battery_are_idle(self):
        self.assertEqual(self.e.tick(PowerSample(PowerState.NO_BATTERY, None, True)), [])
        self.assertEqual(self.e.tick(PowerSample(PowerState.UNKNOWN, None, None)), [])

    def test_threshold_99_has_no_override_button_path(self):
        e = AlertEngine(Config(high_threshold=99), clock=self.clock)
        out = e.tick(S(CH, 99))
        self.assertTrue(out[0].final)
        self.assertFalse(e.handle_action(Action.CHARGE_99))


class OtherTests(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(classify(0, 1, 70).state, DIS)
        self.assertEqual(classify(1, 9, 70).state, CH)
        self.assertEqual(classify(1, 1, 100).state, AC)
        self.assertEqual(classify(1, 128, 255).state, PowerState.NO_BATTERY)
        self.assertEqual(classify(255, 255, 255).state, PowerState.UNKNOWN)
        self.assertEqual(classify(255, 0, 50).state, PowerState.UNKNOWN)

    def test_config_repair(self):
        cfg, changed = parse_config({"low_threshold": 90, "high_threshold": 50, "enabled": "yes"})
        self.assertTrue(changed)
        self.assertEqual(cfg, Config())
        cfg, changed = parse_config(Config().to_dict())
        self.assertFalse(changed)

    def test_uri(self):
        self.assertEqual(parse_action_uri("koustav-laptopbattery://action/charge99"), Action.CHARGE_99)
        self.assertEqual(parse_action_uri("koustav-laptopbattery://action/charge99/"), Action.CHARGE_99)
        self.assertIsNone(parse_action_uri("koustav-laptopbattery://action/rm_rf"))
        self.assertIsNone(parse_action_uri("http://action/charge99"))


if __name__ == "__main__":
    unittest.main()
