from collections import defaultdict
import gym
import gym.spaces
import numpy as np
import random

from gym_sandbox.envs.plot.balls_game_dashboard import BallsNotebookRender
from gym_sandbox.envs.plot.balls_bokeh_serve import BallsBokehServeRender

MOVE_ACTIONS = [[0, -1], [0, 1], [-1, 0], [1, 0]]  # up/down/left/right
GRID_CHANNELS = {
    "police": {
        "num": 0  # total police count
    },
    "thief": {
        "num": 1  # total thief count
    }
}
GRID_DEPTH = sum([len(_c) for _c in GRID_CHANNELS.values()])  # num of channels


class PoliceKillAllEnv(gym.Env):
    """
    Police catch Thief
    Copied from multiagent_balls, difference is
    1. police must kill all thief
    2. only support grid state! because thief list order is not managed
    """
    metadata = {'render.modes': ['human', 'rgb_array']}

    def __init__(self, agent_num=5, agent_team="police", adversary_num=2, map_size=200,
                 adversary_action="static", state_format='grid3d',
                 police_speed=2, thief_speed=1,
                 grid_scale=2, min_catch_dist=3,
                 action_type='discret'):
        """the init params should be passed in by code of env registering
        agent_team: police/thief
        state_format: grid3d/grid3d_ravel/cord_list_unfixed/cord_list_fixed_500
        adversary_action: static/simple/random
        action_type: discret/continous_angle/continous_vector
        Note: for simplicity, the map is a square
        """
        self.teams = {
            "police": {"speed": police_speed},
            "thief": {"speed": thief_speed},
        }
        self.grid_scale=grid_scale
        self.min_catch_dist=min_catch_dist
        self.game_dashboard = None

        self.map_size = map_size
        self.adversary_team = "thief" if agent_team == 'police' else 'police'
        self.agent_num = agent_num
        self.agent_team = agent_team
        self.adversary_num = adversary_num
        self.team_size = {
            self.agent_team: agent_num,
            self.adversary_team: adversary_num
        }
        self.adversary_action = adversary_action
        self.action_type = action_type

        # police thief location
        _map_center = int(self.map_size / 2)
        _police_radius = int(self.map_size * 0.1)
        self._police_range = _map_center - _police_radius, _map_center + _police_radius
        _thief_radius = int(self.map_size * 0.4)
        self._thief_range = _map_center - _thief_radius, _map_center + _thief_radius

        self.state_format = state_format

        # performance wrapper
        self.episode_count = 0
        self.last_state = None
        self.current_state = None
        self.current_action = None
        self.reward_hist = []
        self.current_is_caught = False  # used for render
        self.elapsed_steps = 0

        # overwrite spaces setup for openai a3c usage.
        # depends on some self.**** variables, so put it at the end of the code block.
        if action_type == "discret":
            self.action_space = gym.spaces.Discrete(len(MOVE_ACTIONS))
        elif action_type == "continous_angle":
            self.action_space = gym.spaces.Box(0, 2*np.pi, [1])  # 2pi is total length of circle
        elif action_type == "continous_vector":
            self.action_space = gym.spaces.Box(-1, 1, [2])  # 2pi is total length of circle
        else:
            self.action_space = None

        if state_format == 'grid3d':
            self.observation_space = gym.spaces.Box(
                float(0), float(1), self._get_zero_grid().shape)
        elif state_format == 'grid3d_ravel':
            self.observation_space = gym.spaces.Box(
                float(0), float(1), self._get_zero_grid().ravel().shape)
        elif state_format == 'cord_list_fixed_500':
            self.observation_space = gym.spaces.Box(
                float(0), float(1), (500*2,))
        elif state_format == 'cord_list_unfixed':
            self.observation_space = gym.spaces.Box(
                float(0), float(1), ((agent_num+adversary_num)*2,))
        else:
            self.observation_space = None

        # for statistic usage
        self.total_reward_last_10 = []

    def init_params(self, show_dashboard=True, bokeh_output="notebook"):
        """to control something after env is made
        bokeh_output:  notebook/standalone"""
        self.game_dashboard = None
        if show_dashboard:
            _render_cls = BallsNotebookRender if bokeh_output == "notebook" \
                else BallsBokehServeRender
            self.game_dashboard = _render_cls(self.map_size, self.team_size)

    def _trans_state(self, state):
        if self.state_format in ('cord_list_unfixed', 'cord_list_fixed_500'):
            # output a fixed size of cord list, if empty, add (0,0)
            result = list()
            for _p in state["police"]:
                result.extend(np.array(_p) / self.map_size)
            for _t in state["thief"]:
                result.extend(np.array(_t) / self.map_size)

            if self.state_format == "cord_list_fixed_500":
                for _ in range(500 - len(state["police"]) - len(state["thief"])):
                    result.extend([0, 0])  # for empty placeholder, add 0,0

            return np.array(result)
        elif self.state_format in ('grid3d', 'grid3d_ravel'):
            channel_grids = self.build_grid(state)
            return channel_grids.ravel() if self.state_format == "grid3d_ravel" else channel_grids

    def _cal_reward(self, kill_num, is_done):
        """
        w.r.t idea of MountainCar
        if no thief caught, always -1
        so that total reward will represent how fast the agent can finish all
        """
        reward = kill_num or -1
        self.reward_hist.append(reward)
        return reward

    def _cal_done(self, state, kill_num):
        all_killed = len(state["thief"]) == 0
        _pass_step_limit = self.elapsed_steps >= self.spec.max_episode_steps
        if _pass_step_limit or all_killed:
            return True

        return False

    def add_one_thief(self):
        thief_loc = (
            random.choice([random.randint(0, self._thief_range[0]),
                           random.randint(self._thief_range[1], self.map_size)]),
            random.choice([random.randint(0, self._thief_range[0]),
                           random.randint(self._thief_range[1], self.map_size)]))
        return thief_loc

    def _reset(self):
        # global observation from god's view
        self.global_ob = {
            # police go from map center, so that it must go toward a random direction to catch thief
            "police": [(random.randint(*self._police_range), random.randint(*self._police_range))
                       for _ in range(self.team_size["police"])],
            # make thief away from center
            "thief": [self.add_one_thief() for _ in range(self.team_size["thief"])],

        }
        self.current_state = self.global_ob  # todo: needs to split ob for each agent in MA
        self.elapsed_steps = 0
        self.episode_count += 1
        self.current_is_caught = False
        self.reward_hist = []  # reward of current ep
        ob = self._trans_state(self.global_ob)
        return ob

    def _close(self):
        pass

    def everybody_move(self, cur_state, police_actions):
        """Run move logic for all, only move, no other action"""
        # the target will run out of me as far as possible
        # either x or y, take care of edge and speed
        if not isinstance(police_actions, (np.ndarray, list)):
            police_actions = [police_actions]  # be compatible with MA env.

        new_state = cur_state.copy()

        thief_list = cur_state['thief']
        police_list = cur_state['police']

        # 1. don't move
        if self.adversary_action == "static":
            thief_new_loc = thief_list
        # 2. simple clever action
        elif self.adversary_action == "simple":
            thief_new_loc = [self._take_simple_action(_thief, police_list, team="thief") for _thief in thief_list]
        # 3. random walk
        else:
            thief_new_loc = [self._take_random_action(_thief, team="thief") for _thief in thief_list]

        # samely, for me, run to get more close to target
        # police_new_loc = [
        # self._take_simple_action(_police, thief_list, team="police") for _police in police_list]
        _move_func = self._police_move_by_discret if self.action_type == 'discret' \
            else self._police_move_by_continous_angle if self.action_type == 'continous_angle' \
            else self._police_move_by_continous_vector
        police_new_loc = _move_func(police_list, police_actions)

        new_state['thief'] = thief_new_loc
        new_state['police'] = police_new_loc
        return new_state

    def _police_move_by_discret(self, police_list, police_actions):
        # Accpet a discret action (up/down/left/right)
        police_new_loc = police_list.copy()
        police_speed = self.teams['police']['speed']
        for _i, _a in enumerate(police_actions):
            if _a < len(MOVE_ACTIONS):  # move, otherwise keep the same
                # TODO: add stop action
                action_dir = np.array(MOVE_ACTIONS[_a])
                police_dir = action_dir * police_speed

                _p = police_list[_i]
                _p = (_p[0] + police_dir[0], _p[1] + police_dir[1])
                _p = self.ensure_inside(_p)
                police_new_loc[_i] = _p

        return police_new_loc

    def _police_move_by_continous_vector(self, police_list, police_actions):
        """accept vector [x, y], both -1~1, fixed length"""
        police_new_loc = police_list.copy()
        police_speed = self.teams['police']['speed']
        for _i, _a in enumerate(police_actions):
            action_dir = np.array(_a).astype(np.float)
            if np.all(action_dir != 0):  # allow 0,0 which means don't move
                _norm_dir = action_dir / np.sqrt(np.sum(action_dir ** 2))  # a excircle
                police_dir = _norm_dir * police_speed
                _p = np.array(police_list[_i]) + police_dir
                _p = self.ensure_inside(_p)
                police_new_loc[_i] = _p

        return police_new_loc

    def _police_move_by_continous_angle(self, police_list, police_actions):
        # Accept continous move action, which is more suitable for MADDPG
        # move angle (0~2pi)
        police_actions = np.clip(police_actions, 0, 2*np.pi)

        police_new_loc = police_list.copy()
        police_speed = self.teams['police']['speed']
        for _i, _a in enumerate(police_actions):
            _a = np.asscalar(_a)  # transform array to scalar
            action_dir = np.array([np.cos(_a), np.sin(_a)])
            police_dir = action_dir * police_speed
            _p = police_list[_i]
            _p = (_p[0] + police_dir[0], _p[1] + police_dir[1])
            _p = self.ensure_inside(_p)
            police_new_loc[_i] = _p

        return police_new_loc

    def _step(self, action):
        """firstly move, then check distance"""
        new_state = self.everybody_move(self.current_state, action)
        new_state, kill_num = self.check_thief_caught(new_state)
        self.current_is_caught = kill_num > 0

        self.last_state = self.current_state
        self.current_state = new_state
        self.current_action = action
        self.elapsed_steps += 1

        ob = self._trans_state(self.current_state)
        self.current_done = self._cal_done(self.current_state, kill_num)
        reward = self._cal_reward(kill_num, self.current_done)

        info = self._get_step_info()

        return ob, reward, self.current_done, info

    def ensure_inside(self, cord):
        x, y = cord
        x = self.map_size if x > self.map_size else 0 if x < 0 else x
        y = self.map_size if y > self.map_size else 0 if y < 0 else y
        return (x, y)

    def check_thief_caught(self, cur_state):
        """override attention: must return thief caught num of this step
        return (new_state, kill_num)
        """
        new_state = cur_state.copy()

        thief_list = new_state['thief']
        police_list = new_state['police']

        survived_thief_list = []
        for _thief in thief_list:
            closed_police = [_p for _p in police_list
                             if self.calc_dist(_thief, _p) <= self.min_catch_dist]
            if not closed_police:
                survived_thief_list.append(_thief)

        new_state['thief'] = survived_thief_list

        kill_num = len(cur_state["thief"]) - len(new_state["thief"])

        return new_state, kill_num

    def _get_avail_new_loc(self, my_pos, my_speed):
        x, y = my_pos
        available_direction = [
            y - my_speed > 0,
            y + my_speed < self.map_size,
            x - my_speed > 0,
            x + my_speed < self.map_size,
        ]
        new_location = [
            (x, y - my_speed),
            (x, y + my_speed),
            (x - my_speed, y),
            (x + my_speed, y),
        ]

        available_loc = [_l for i, _l in enumerate(new_location) if available_direction[i]]
        return available_loc

    def _take_simple_action(self, my_pos, adversary_list, team="thief"):
        """take a little clever action"""
        available_loc = self._get_avail_new_loc(my_pos, self.teams[team]['speed'])

        new_dist = [self.get_position_rating(my_new_pos, adversary_list) for my_new_pos in available_loc]

        func = max if team == "thief" else min
        best_choice = func(enumerate(new_dist), key=lambda x: x[1])[0]
        my_final_pos = available_loc[best_choice]
        return my_final_pos

    def _take_random_action(self, my_pos, team="thief"):
        """Take a random walk"""
        available_loc = self._get_avail_new_loc(my_pos, self.teams[team]['speed'])
        return random.choice(available_loc)

    def _render(self, mode='human', close=False):
        if not self.current_state:
            return

        env_data = [self.current_state, self.reward_hist, self.episode_count,
                    len(self.reward_hist), self.current_action, self.current_is_caught, self.current_done]
        if self.game_dashboard:
            self.game_dashboard.update_plots(env_data)
        return

    def get_position_rating(self, my_new_pos, adversary_list):
        all_dist = [self.calc_dist(my_new_pos, _ad) for _ad in adversary_list]
        return sum(all_dist)

    def calc_dist(self, pos1, pos2):
        """manhatton dist"""
        _coords1 = np.array(pos1)  # location of me
        _coords2 = np.array(pos2)
        return np.sum(abs(_coords1 - _coords2))

        # # calc Euclidean Distance
        # # alternative way: np.linalg.norm(_coords1 - _coords2)
        # eucl_dist = np.sqrt(np.sum((_coords1 - _coords2) ** 2))
        # return eucl_dist

    def _get_zero_grid(self):
        grid_num = self.map_size * self.grid_scale
        thematrix = np.zeros((grid_num, grid_num, GRID_DEPTH))
        return thematrix

    def build_grid(self, state):
        """transform raw state into a grid-based n-depth matrix"""
        # a grid with depth/channel like a image file
        # grid size is 2 times of map size, to make 4 points of 1x1 map can be split into 4 seperate grid
        # attention: all grid closed to edge must include position on edge line!

        # step1. construct a matrix of data object
        thematrix = self._get_zero_grid()

        # step2. analyze state and append data attribute to each object

        # 2.1 split axis by grid num

        # 2.2 add up player's and npc data

        for team in self.teams.keys():
            for _p in state[team]:
                _grid_cord = self._get_grid_cord(_p)

                _channel = GRID_CHANNELS[team]["num"]
                thematrix[tuple(_grid_cord)][_channel] += 1

        thematrix[:, :, GRID_CHANNELS["thief"]["num"]] /= self.adversary_num

        return thematrix

    def _get_grid_cord(self, raw_cord):
        """According to raw axis position, calc new grid cordination
        note 1 is the raw grid size
        """
        new_scaled_cord = np.array(raw_cord) * self.grid_scale
        new_scaled_cord = new_scaled_cord.astype(int)  # transform to grid number

        # handle max edge
        for _axis in [0, 1]:
            if new_scaled_cord[_axis] == self.map_size * self.grid_scale:
                new_scaled_cord[_axis] = new_scaled_cord[_axis] - 1
        return new_scaled_cord

    def close(self, *args, **kwargs):
        pass  # close will trigger render(don't need it in many case)

    def _get_step_info(self):
        info = {}
        if self.current_done:
            total_reward = sum(self.reward_hist)
            self.total_reward_last_10.append(total_reward)
            if len(self.total_reward_last_10) > 10:
                self.total_reward_last_10.pop(0)

            info["total_reward"] = total_reward
            info["total_steps"] = self.elapsed_steps
            info["total_episode"] = self.episode_count
            info["total_reward_average_last_10"] = sum(self.total_reward_last_10) / len(self.total_reward_last_10)

        return info
