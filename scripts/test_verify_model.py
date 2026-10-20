"""Mutation checks: demonstrate that model acceptance detects material defects.

All mutations are in-memory strings; upstream model/data files stay untouched.
Run: python -m unittest discover -s scripts -p test_verify_model.py
"""
from pathlib import Path
import unittest

from verify_model import (ROOT, communication_checks, control_flow_checks,
                          isolation_checks, policy_checks, probability_checks,
                          procedures, tokens, verify)


def source(index):
    path, = (ROOT / 'models' / f'experiment_{index}').glob('*.nls')
    return path.read_text(encoding='utf-8-sig')


class ModelAcceptanceMutations(unittest.TestCase):
    def test_pinned_scientific_release_passes_all_static_checks(self):
        result = verify(ROOT)
        self.assertTrue(result['passed'])
        self.assertEqual(len(result['models']), 3)

    def test_real_likelihood_error_is_detected_without_hash_shortcut(self):
        wrong = source(1).replace('set llr-unit ln (p-b-good / p-b-bad)',
                                  'set llr-unit ln (p-b-bad / p-b-good)')
        with self.assertRaisesRegex(AssertionError, 'log likelihood'):
            probability_checks(procedures(wrong))

    def test_B_failure_with_wrong_sign_fails_exact_rational_oracle(self):
        wrong = source(1).replace('set belief-llr belief-llr - llr-unit',
                                  'set belief-llr belief-llr + llr-unit')
        with self.assertRaisesRegex(AssertionError, 'Exact Bayes posterior'):
            probability_checks(procedures(wrong))

    def test_duplicate_message_reprocessing_is_detected(self):
        wrong = source(1).replace('ifelse member? evidence-id seen-evidence-ids',
                                  'ifelse false')
        with self.assertRaisesRegex(AssertionError, 'Duplicate peer message'):
            communication_checks(procedures(wrong))

    def test_passing_on_an_inbox_instead_of_own_result_is_detected(self):
        wrong = source(1).replace('(list (list who ticks 0) chose-b? current-reward)',
                                  '(list (list who ticks 0) chose-b? next-inbox)')
        with self.assertRaisesRegex(AssertionError, 'relayed/private evidence'):
            communication_checks(procedures(wrong))

    def test_dropping_peer_delivery_breaks_parsed_control_flow(self):
        wrong = source(1).replace('if ticks < total-ticks-fixed [deliver-peer-messages]',
                                  'if ticks > total-ticks-fixed [deliver-peer-messages]')
        with self.assertRaises((ValueError, AssertionError)):
            control_flow_checks(procedures(wrong))

    def test_P_incorrectly_retaining_local_data_is_detected(self):
        wrong = source(1).replace('set decision-base-llr processed-packet-llr',
                                  'set decision-base-llr pre-intervention-llr + processed-packet-llr')
        with self.assertRaisesRegex(AssertionError, 'Evidence policy exact posterior'):
            policy_checks(procedures(wrong))

    def test_hiding_true_world_inside_called_reporter_is_detected(self):
        wrong = source(1).replace('report 1 / (1 + exp (0 - llr))',
                                  'if hidden-world = "B-good" [report 1]\n  report 0')
        with self.assertRaisesRegex(AssertionError, 'Hidden scoring input'):
            isolation_checks(procedures(wrong))

    def test_opaque_recipient_cannot_read_private_expert_q(self):
        wrong = source(2).replace('let payload-llr received-message-llr',
                                  'let payload-llr private-expert-q-at-intervention')
        with self.assertRaisesRegex(AssertionError, 'Opaque recipient'):
            isolation_checks(procedures(wrong))

    def test_unrecognized_syntax_fails_closed_and_comments_are_not_code(self):
        self.assertEqual(tokens('report "hidden-world" ; hidden-world\n'),
                         ['report', '"hidden-world"'])
        with self.assertRaisesRegex(AssertionError, 'Unsupported source'):
            tokens('report @unsupported')


if __name__ == '__main__':
    unittest.main()
