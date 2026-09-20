"""测试支线同步事件回归检查。"""

import unittest

from tasks.Chess.test_branch.decision import ChessAction, ChessDecision
from tasks.Chess.test_branch.events import ChessEventKind, ChessEventMonitor
from tasks.Chess.test_branch.state import ChessGameState


class ChessEventTest(unittest.TestCase):
    def test_edges_and_reset(self):
        state = ChessGameState()
        progress = state.begin_round(2)
        monitor = ChessEventMonitor()
        observation = state.observe('f1', round_no=2, mode='备')
        events = monitor.collect(observation, grigri_visible=True)
        self.assertEqual(
            [event.kind for event in events],
            [ChessEventKind.MODE_CHANGED, ChessEventKind.GRIGRI_OPENED],
        )
        self.assertEqual(monitor.collect(observation, grigri_visible=True), ())
        decision = ChessDecision(ChessAction.NEXT_ROUND, progress, '战', 3)
        observation = state.observe('f2', round_no=3, mode='战')
        events = monitor.collect(observation, decision=decision)
        self.assertEqual(
            [event.kind for event in events],
            [ChessEventKind.MODE_CHANGED, ChessEventKind.ROUND_CONFIRMED],
        )
        self.assertEqual(monitor.collect(observation, game_ended=True)[0].kind,
                         ChessEventKind.GAME_ENDED)
        monitor.reset()
        self.assertEqual(monitor.collect(observation)[0].kind,
                         ChessEventKind.MODE_CHANGED)


if __name__ == '__main__':
    unittest.main()
