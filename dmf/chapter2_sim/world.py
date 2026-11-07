"""Action-dependent synthetic dynamics and independent hidden arrival reference."""
import numpy as np

from .config import SCENARIOS


class DropletWorld:
    def __init__(self, config, geometry, scenario, seed):
        if scenario not in SCENARIOS:
            raise ValueError('unknown scenario: ' + scenario)
        self.cfg, self.map, self.scenario = config, geometry, scenario
        self.position = geometry.center(config.route[0])
        self.velocity = np.zeros(2)
        self.time = 0.
        self.pending = []
        self.active = None
        self.start = self.position.copy()
        self.goal = self.position.copy()
        self.response_at = float('inf')
        self.attempts = {}
        self.settled_since = {}
        self.arrival_times = {}
        # Tick-indexed exogenous process, independent of command/observation count.
        rng = np.random.default_rng(np.random.SeedSequence([seed, 101]))
        self.noise = rng.normal(size=(int(config.max_time_s/config.dt_s)+1000, 2))
        self.speed_factor = float(rng.uniform(.8, 1.2))

    def command(self, target, time_s, action):
        applied = time_s + self.cfg.ack_delay_s
        self.pending.append((applied, target, action))
        return applied

    def _apply(self, applied, target, action):
        cfg = self.cfg
        self.active = target
        self.start = self.position.copy()
        self.goal = self.map.center(target)
        if action != 'Recovery':
            self.attempts[target] = self.attempts.get(target, 0) + 1
        first = self.attempts.get(target, 0) == 1 and action != 'Recovery'
        self.response_at = applied + (1.15 if self.scenario == 'delayed' else cfg.response_delay_s)
        if self.scenario == 'partial_stall' and first:
            self.goal = self.start + .58*(self.goal-self.start)
        if self.scenario == 'deviation' and first:
            direction = self.goal-self.start
            norm = np.linalg.norm(direction)
            if norm:
                self.goal = self.goal + .8*np.array([-direction[1], direction[0]])/norm
        if self.scenario == 'failure' and action != 'Recovery':
            self.goal = self.start.copy()

    def advance(self, until_s):
        if until_s < self.time - 1e-9:
            raise ValueError('physics cannot travel backwards')
        cfg = self.cfg
        while self.time < until_s - 1e-10:
            end = min(until_s, self.time + cfg.dt_s)
            dt = end-self.time
            while self.pending and self.pending[0][0] <= self.time + 1e-9:
                self._apply(*self.pending.pop(0))
            old = self.position.copy()
            if self.time >= self.response_at:
                delta = self.goal-self.position
                distance = np.linalg.norm(delta)
                step = cfg.speed*self.speed_factor*dt
                if distance > 1e-10:
                    self.position += delta*min(1., step/distance)
                    if distance > .12:
                        tick = min(int(round(self.time/cfg.dt_s)), len(self.noise)-1)
                        self.position += cfg.process_noise*np.sqrt(dt)*self.noise[tick]
            self.velocity = (self.position-old)/dt
            self.time = end
            # Reference is physical basin + true speed + dwell; no mask or
            # recognition/config arrival thresholds are inspected here.
            for electrode in set(cfg.route):
                inside = (np.linalg.norm(self.position-self.map.center(electrode)) <= cfg.truth_radius
                          and np.linalg.norm(self.velocity) <= cfg.truth_max_speed)
                if inside:
                    self.settled_since.setdefault(electrode, self.time)
                    if self.time-self.settled_since[electrode] >= cfg.truth_dwell_s-1e-9:
                        self.arrival_times.setdefault(electrode, self.time)
                else:
                    self.settled_since.pop(electrode, None)

    def is_physically_settled(self, electrode):
        return electrode in self.settled_since and self.time-self.settled_since[electrode] >= self.cfg.truth_dwell_s-1e-9
