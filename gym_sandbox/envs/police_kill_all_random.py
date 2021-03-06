from collections import defaultdict
import gym
import gym.spaces
import numpy as np
import random

from .police_base import PoliceKillAllEnv
from gym_sandbox.envs.plot import balls_game_dashboard


class RandomBallsEnv(PoliceKillAllEnv):
    """
    Focus to add more randomness into env
    Feature:
    1. Thief are incremently added into map in each step
    2. Each add batch has random num of thief
    3. Thief walk in a random way
    """
    def __init__(self, init_thief_num=1, step_add_thief_max=3, **kwargs):
        super().__init__(**kwargs)

        self.step_add_thief_max = step_add_thief_max
        self.init_thief_num = init_thief_num
        self.team_size[self.adversary_team] = init_thief_num
        self.rest_thief_num = self.adversary_num - init_thief_num

    def _step(self, action):
        # add some thief in
        random_num = random.choice(range(1, self.step_add_thief_max))
        add_num = min(random_num, self.rest_thief_num)
        self.rest_thief_num -= add_num
        for i in range(add_num):
            self.current_state['thief'].append(self.add_one_thief())

        return super()._step(action)

    def _reset(self):
        self.rest_thief_num = self.adversary_num - self.init_thief_num
        return super()._reset()

    def _cal_done(self, state, kill_num):
        all_killed = self.rest_thief_num <= 0 and len(state["thief"]) == 0
        _pass_step_limit = self.elapsed_steps >= self.spec.max_episode_steps
        if _pass_step_limit or all_killed:
            return True

        return False
