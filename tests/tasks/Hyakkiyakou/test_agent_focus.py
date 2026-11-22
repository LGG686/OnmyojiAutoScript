import numpy as np

from tasks.Hyakkiyakou.agent.agent import Agent
from tasks.Hyakkiyakou.agent.focus import Focus

# 2026-11-21 14:36:42 崩溃帧：两个 class=0 的框都不会画进热力图，
# 最后一个框中心 x=1320，画面宽 1280。
OFFSCREEN_FRAME = [
    (41, 0, 0.9723028540611267, 847, 293, 41, 98, 0.041499774903059006),
    (45, 0, 0.6597861051559448, 1320, 404, 64, 99, 0.3642634451389313),
]


def test_empty_heatmap_does_not_focus_the_last_offscreen_track():
    agent = Agent()
    z = Agent.gamma(OFFSCREEN_FRAME, weights=agent.weights, priorities=agent.priorities)

    assert Agent.argmax_gamma(z, OFFSCREEN_FRAME) is None

    agent.check_observe(OFFSCREEN_FRAME)
    assert agent.focus is None


def test_focus_outside_the_frame_reads_as_no_observation():
    focus = Focus(inputs=OFFSCREEN_FRAME[-1])
    z = np.zeros((720, 1280), dtype=np.float32)

    assert focus.omega(z) == 0.0
