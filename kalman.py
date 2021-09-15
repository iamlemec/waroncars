import numpy as np
import pandas as pd

from operator import itemgetter
from collections import deque

# simple kalman filter
# no control (B = u = 0)
# no model noise (Q = w = 0)
class KalmanTracker:
    def __init__(self, ndim, σz, σv):
        self.ndim = ndim

        self.I = np.eye(ndim)
        self.Z = np.zeros((ndim, ndim))
        self.H = np.block([self.I, self.Z])

        self.R = np.diag(np.square(σz))
        Pv = np.diag(np.square(σv))
        self.P0 = np.block([
            [self.R, self.Z],
            [self.Z, Pv]
        ])

    def start(self, z):
        vel = np.zeros(self.ndim)

        x = np.hstack([z, vel])
        P = self.P0

        return x, P

    def update(self, x, P, z, dt=1):
        x1, P1 = self.predict(x, P, dt=dt)

        A = self.H @ P1 @ self.H.T + self.R
        B = P1 @ self.H.T
        K = np.linalg.solve(A, B.T).T

        I = np.eye(2*self.ndim)
        G = I - K @ self.H

        x2 = G @ x1 + K @ z
        P2 = G @ P1

        return x2, P2

    def predict(self, x, P, dt=1):
        F = np.block([
            [self.I, dt*self.I],
            [self.Z, self.I]
        ])

        x1 = F @ x
        P1 = F @ P @ F.T

        return x1, P1

##
## object tracking
##

def box_area(l, t, r, b):
    w = np.maximum(0, r-l)
    h = np.maximum(0, b-t)
    return w*h

def box_overlap(box1, box2):
    l1, t1, r1, b1 = box1
    l2, t2, r2, b2 = box2

    lx = np.maximum(l1, l2)
    tx = np.maximum(t1, t2)
    rx = np.minimum(r1, r2)
    bx = np.minimum(b1, b2)

    a1 = box_area(l1, t1, r1, b1)
    a2 = box_area(l2, t2, r2, b2)
    ax = box_area(lx, tx, rx, bx)

    sim = ax/np.maximum(a1, a2)
    return 1 - sim

kalman_args = {
    'ndim': 4,
    'σz': [0.05, 0.05, 0.05, 0.05],
    'σv': [0.5, 0.5, 0.5, 0.5],
}

# single object state
class Track:
    def __init__(self, kalman, length, l, t, z):
        self.kalman = kalman
        self.l = l
        self.t = t
        self.x, self.P = kalman.start(z)
        self.hist = deque([(t, z, self.x, self.P)], length)

    def predict(self, t):
        dt = t - self.t
        x1, P1 = self.kalman.predict(self.x, self.P, dt=dt)
        return x1, P1

    def update(self, t, z):
        dt = t - self.t
        self.t = t
        self.x, self.P = self.kalman.update(self.x, self.P, z, dt=dt)
        self.hist.append((t, z, self.x, self.P))

    def dataframe(self):
        return pd.DataFrame(
            np.vstack([np.hstack(h[:3]) for h in self.hist]),
            columns=[
                't', 'x', 'y', 'w', 'h',
                'kx', 'ky', 'kw', 'kh',
                'vx', 'vy', 'vw', 'vh'
            ]
        )

# entry: index, label, qual, coords
class BoxTracker:
    def __init__(self, timeout=2.0, cutoff=0.2, length=250):
        self.timeout = timeout
        self.cutoff = cutoff
        self.length = length
        self.kalman = KalmanTracker(**kalman_args)
        self.reset()

    def reset(self):
        self.nextid = 0
        self.tracks = {}

    def add(self, l, t, z):
        i = self.nextid
        self.nextid += 1
        self.tracks[i] = Track(self.kalman, self.length, l, t, z)
        return i

    def pop(self, i):
        return self.tracks.pop(i)

    def update(self, t, boxes):
        # precompute predicted positions for tracks
        locs = {i: trk.predict(t) for i, trk in self.tracks.items()}

        # compute all pairs with difference below cutoff
        errs = []
        for k1, (l1, c1) in enumerate(boxes):
            for i2, trk in self.tracks.items():
                x1, P1 = locs[i2]
                l2, c2 = trk.l, x1[:4]
                if l1 == l2:
                    e = box_overlap(c1, c2) # this can be improved
                    if e < self.cutoff:
                        errs.append((k1, i2, e))

        # unravel match in decreasing order of similarity
        final = []
        for _ in range(len(errs)):
            k, j, e = min(errs, key=itemgetter(2))
            final.append((k, j, e))
            errs = [(k1, j1, e1) for k1, j1, e1 in errs if k1 != k and j1 != j]
            if len(errs) == 0:
                break

        # update positive matches
        mapper = {}
        for k, j, e in final:
            _, c = boxes[k]
            self.tracks[j].update(t, c)
            mapper[k] = j

        # create new tracks for non-matches
        match = []
        for k, (l, c) in enumerate(boxes):
            if k not in mapper:
                mapper[k] = self.add(l, t, c)
            match.append(mapper[k])

        # clear out old tracks
        idone = [
            i for i, trk in self.tracks.items() if t > trk.t + self.timeout
        ]
        done = {i: self.tracks.pop(i) for i in idone}

        # return matches and final tracks
        return match, done
