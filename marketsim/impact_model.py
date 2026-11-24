"""Event-impact model: what will the market's reaction to a filing be? (real-data experiment)

Two small models, trained on past events only, fitted with NumPy / SciPy:

* **Direction (classification):** multinomial logistic regression with L2, three classes for the
  abnormal return on the reaction day: *down* (< −τ), *flat*, *up* (> τ).
* **Size (regression):** ridge regression of log |abnormal return|, so the model knows earnings
  move the stock far more than a shareholder vote does. The residual spread makes it a
  lognormal size distribution.

Features are standardised with training means and sds. `sample` draws reactions from the
predicted distribution (class, then size), which is how the simulation and the event-aware
random walk turn a predicted event into a price jump.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize

CLASSES = ("down", "flat", "up")


@dataclass
class ImpactModel:
    tau: float = 0.01  # |abnormal return| below this counts as flat
    l2: float = 1.0
    size_l2: float = 3.0
    mu: np.ndarray = field(default_factory=lambda: np.zeros(0))
    sd: np.ndarray = field(default_factory=lambda: np.ones(0))
    W: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    b: np.ndarray = field(default_factory=lambda: np.zeros(3))
    size_w: np.ndarray = field(default_factory=lambda: np.zeros(0))
    size_b: float = -4.0
    size_sigma: float = 0.8

    def _z(self, X: np.ndarray) -> np.ndarray:
        return (np.asarray(X, np.float64) - self.mu) / self.sd

    @staticmethod
    def classes_of(y: np.ndarray, tau: float) -> np.ndarray:
        y = np.asarray(y, np.float64)
        return np.where(y < -tau, 0, np.where(y > tau, 2, 1))

    def fit(self, X: np.ndarray, y: np.ndarray) -> ImpactModel:
        X = np.asarray(X, np.float64)
        y = np.asarray(y, np.float64)
        self.mu = X.mean(axis=0)
        self.sd = X.std(axis=0)
        self.sd[self.sd < 1e-9] = 1.0
        Z = self._z(X)
        n, k = Z.shape
        c = self.classes_of(y, self.tau)
        Y = np.eye(3)[c]

        def loss(theta: np.ndarray) -> tuple[float, np.ndarray]:
            W = theta[: k * 3].reshape(k, 3)
            b = theta[k * 3 :]
            logits = Z @ W + b
            logits -= logits.max(axis=1, keepdims=True)
            p = np.exp(logits)
            p /= p.sum(axis=1, keepdims=True)
            nll = -np.sum(Y * np.log(p + 1e-12)) / n + 0.5 * self.l2 * np.sum(W * W) / n
            g = (p - Y) / n
            gW = Z.T @ g + self.l2 * W / n
            return float(nll), np.concatenate([gW.ravel(), g.sum(axis=0)])

        res = minimize(loss, np.zeros(k * 3 + 3), jac=True, method="L-BFGS-B")
        self.W = res.x[: k * 3].reshape(k, 3)
        self.b = res.x[k * 3 :]
        # size: ridge on log |y|
        t = np.log(np.abs(y) + 1e-3)
        A = np.c_[Z, np.ones(n)]
        reg = self.size_l2 * np.eye(k + 1)
        reg[-1, -1] = 0.0
        coef = np.linalg.solve(A.T @ A + reg, A.T @ t)
        self.size_w, self.size_b = coef[:-1], float(coef[-1])
        resid = t - A @ coef
        self.size_sigma = float(max(resid.std(ddof=1), 0.2)) if n > 2 else 0.8
        return self

    def proba(self, X: np.ndarray) -> np.ndarray:
        logits = self._z(X) @ self.W + self.b
        logits -= logits.max(axis=1, keepdims=True)
        p = np.exp(logits)
        return p / p.sum(axis=1, keepdims=True)

    def size(self, X: np.ndarray) -> np.ndarray:
        """Median |abnormal return| (lognormal centre)."""
        return np.maximum(np.exp(self._z(X) @ self.size_w + self.size_b) - 1e-3, 1e-4)

    def expected(self, X: np.ndarray) -> np.ndarray:
        """Expected signed reaction: (P(up) − P(down)) × mean size."""
        p = self.proba(X)
        mean_size = self.size(X) * np.exp(0.5 * self.size_sigma**2)
        return (p[:, 2] - p[:, 0]) * mean_size

    def sample(self, X: np.ndarray, rng: np.random.Generator, k: int = 1) -> np.ndarray:
        """(k, n) reactions drawn from the predicted distribution."""
        p = self.proba(X)
        m = self.size(X)
        n = len(m)
        u = rng.random((k, n))
        cls = (u > p[:, 0]).astype(int) + (u > p[:, 0] + p[:, 1]).astype(int)
        mag = m * np.exp(self.size_sigma * rng.standard_normal((k, n)))
        flat = rng.normal(0.0, self.tau / 2, (k, n))
        return np.where(cls == 2, mag, np.where(cls == 0, -mag, flat))

    def evaluate(self, X: np.ndarray, y: np.ndarray, train_y: np.ndarray) -> dict[str, float]:
        """Accuracy and log loss against the training base rates, size error against a constant."""
        c = self.classes_of(y, self.tau)
        p = self.proba(X)
        base = np.bincount(self.classes_of(train_y, self.tau), minlength=3) / max(len(train_y), 1)
        nonflat = c != 1
        pred_dir = np.where(p[:, 2] >= p[:, 0], 2, 0)
        size_true = np.log(np.abs(y) + 1e-3)
        size_pred = np.log(self.size(X) + 1e-3)
        const = np.median(np.log(np.abs(train_y) + 1e-3))
        return {
            "n": len(y),
            "accuracy": float((p.argmax(axis=1) == c).mean()) if len(y) else float("nan"),
            "majority_accuracy": float((c == int(np.argmax(base))).mean()) if len(y) else float("nan"),
            "log_loss": float(-np.mean(np.log(p[np.arange(len(c)), c] + 1e-12))) if len(y) else float("nan"),
            "base_rate_log_loss": float(-np.mean(np.log(base[c] + 1e-12))) if len(y) else float("nan"),
            "direction_hit_rate": float((pred_dir[nonflat] == c[nonflat]).mean())
            if nonflat.any()
            else float("nan"),
            "n_moves": int(nonflat.sum()),
            "size_mae_log": float(np.mean(np.abs(size_pred - size_true))) if len(y) else float("nan"),
            "constant_size_mae_log": float(np.mean(np.abs(const - size_true))) if len(y) else float("nan"),
            "size_corr": float(np.corrcoef(size_pred, size_true)[0, 1]) if len(y) > 2 else float("nan"),
        }
