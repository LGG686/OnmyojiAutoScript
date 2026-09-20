"""测试支线决策层的无设备回归检查。"""

import unittest

from tasks.Chess.test_branch.decision import ChessAction, decide_round
from tasks.Chess.test_branch.state import ChessGameState


class ChessDecisionTest(unittest.TestCase):
    def setUp(self):
        self.state = ChessGameState()
        self.progress = self.state.begin_round(2)

    def decide(self, frame, **values):
        observation = self.state.observe(frame, **values)
        return decide_round(
            observation, self.progress, now=100.0,
            confirm_frames=2, unknown_timeout=5.0,
            in_game=True, grigri_visible=False,
        )

    def test_round_change_requires_two_frames_and_preserves_input(self):
        first = self.decide('f1', round_no=3, mode='备')
        self.assertEqual(first.action, ChessAction.ROUND_PENDING)
        self.assertIsNone(self.progress.next_round_candidate)
        self.progress = first.progress
        second = self.decide('f2', round_no=3, mode='备')
        self.assertEqual(second.action, ChessAction.NEXT_ROUND)
        self.assertEqual(second.next_round, 3)

    def test_round_candidate_resets_when_number_returns(self):
        self.progress = self.decide('f1', round_no=3).progress
        decision = self.decide('f2', round_no=2, mode='备')
        self.assertEqual(decision.action, ChessAction.PREPARE)
        self.assertIsNone(decision.progress.next_round_candidate)

    def test_grigri_takes_priority_over_preparation(self):
        observation = self.state.observe('f1', round_no=2, mode='备')
        decision = decide_round(
            observation, self.progress, now=100.0,
            confirm_frames=2, unknown_timeout=5.0,
            in_game=True, grigri_visible=True,
        )
        self.assertEqual(decision.action, ChessAction.RESOLVE_GRIGRI)

    def test_battle_and_passive_modes(self):
        self.assertEqual(self.decide('f1', mode='战').action, ChessAction.BATTLE)
        self.assertEqual(self.decide('f2', mode='鬼').action, ChessAction.PASSIVE)

    def test_marker_timeout(self):
        observation = self.state.observe('f1', round_no=2)
        first = decide_round(
            observation, self.progress, now=100.0,
            confirm_frames=2, unknown_timeout=5.0,
            in_game=False, grigri_visible=False,
        )
        second = decide_round(
            observation, first.progress, now=105.0,
            confirm_frames=2, unknown_timeout=5.0,
            in_game=False, grigri_visible=False,
        )
        self.assertEqual(first.action, ChessAction.WAIT)
        self.assertEqual(second.action, ChessAction.LOST_MARKERS)


if __name__ == '__main__':
    unittest.main()
