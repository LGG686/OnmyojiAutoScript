"""无需启动模拟器的 Chess 状态层回归检查。"""

import unittest

from tasks.Chess.test_branch.state import ChessGameState


class ChessGameStateTest(unittest.TestCase):
    def test_observation_keeps_fields_only_within_same_frame(self):
        state = ChessGameState()
        first = state.observe('frame-1', round_no=2)
        same = state.observe('frame-1', mode='备')
        next_frame = state.observe('frame-2', mode='战')

        self.assertEqual((first.round_no, first.mode), (2, None))
        self.assertEqual((same.round_no, same.mode), (2, '备'))
        self.assertEqual((next_frame.round_no, next_frame.mode), (None, '战'))
        self.assertEqual(state.observation, next_frame)

    def test_new_round_resets_only_round_progress(self):
        state = ChessGameState()
        state.begin_game()
        state.economy_pending = True
        old_round = state.begin_round(3)
        old_round.hyakki_round_seen = True

        new_round = state.begin_round(4)
        self.assertTrue(state.economy_pending)
        self.assertEqual(new_round.round_no, 4)
        self.assertFalse(new_round.hyakki_round_seen)

    def test_new_game_resets_all_transient_state(self):
        state = ChessGameState()
        state.begin_game()
        state.begin_round(4)
        state.economy_pending = True
        state.board_lineup_names.add('test')
        state.observe('frame-1', mode='鬼')

        state.begin_game()
        self.assertEqual(state.game_number, 2)
        self.assertIsNone(state.round)
        self.assertIsNone(state.observation)
        self.assertFalse(state.economy_pending)
        self.assertEqual(state.board_lineup_names, set())


if __name__ == '__main__':
    unittest.main()
