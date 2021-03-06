# gym-sandbox
- Customize your own gym environment to simulate any RL problem you want to solve.
- Principle: don't introduce any complexity, focus on algo test!
- Similar project: https://github.com/deepmind/pycolab

## How to use
1. git clone this repo
2. cd into repo
3. pip install -e .
4. Switch to your algo, and `import gym_sandbox ; gym.make("xxx-v0")`
    - all xxx env are in `env_list.py` of root dir.
    - Please do note that now env requires jupyter notebook

## Code structure
- `env_list.py`  >> contains all env you can use
- envs         >> core code of envs
- test_algos   >> demo algos to solve the env, note it's just demo!
- test         >> unittests

## Philosophy
Divide and Conquer.
- Divide complex real problem into clean focused sub-tasks, and conquer by each.

Pipeline.
- Integrate your solutions of all sub-tasks.

## Origin
We want to solve complex games, like StarCraft, SuperMario, etc.
However, these games contains many sub-tasks, if we can't solve one, we can't solve the whole.
So we must ensure we can solve each sub-task, and then we have the confidence to solve all.

## Features
- OpenAI Gym
    - 100% compatible
- Bokeh
    - We use bokeh to render game state, which is clean, intuitive, and
- Multi-agent
    - Inspired by MADDPG

## Credit
OpenAI's universe-starter-agent is a very cool project, where there're many good point of engineering design.


