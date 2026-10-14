
"""Context-aware hotel recommenders for Voyage Analytics (shared by the notebook, MLflow and the web app)."""
import numpy as np
import pandas as pd


class HotelRecommender:
    """Hybrid recommender: user-based collaborative filtering + the user's own history + popularity.

    Context rules applied at recommendation time:
      * never suggest the hotel in the departure (origin) city,
      * optionally keep only the destination city's hotel and/or hotels within a budget.
    Unknown users get popularity-based suggestions (cold start).
    """

    def __init__(self, k_neighbors=50, w_cf=1.0, w_history=0.0, w_pop=0.0, pop_window_days=None):
        self.k_neighbors = k_neighbors
        self.w_cf, self.w_history, self.w_pop = w_cf, w_history, w_pop
        self.pop_window_days = pop_window_days

    def fit(self, bookings, catalog):
        """bookings: userCode, name, date | catalog: name, place, price"""
        self.catalog_ = catalog.set_index('name')[['place', 'price']].copy()
        self.hotels_ = list(self.catalog_.index)
        recent = bookings
        if self.pop_window_days:
            cutoff = bookings['date'].max() - pd.Timedelta(days=self.pop_window_days)
            recent = bookings[bookings['date'] >= cutoff]
            if recent.empty:
                recent = bookings
        pop = recent['name'].value_counts().reindex(self.hotels_, fill_value=0).astype(float)
        self.popularity_ = (pop / pop.sum()).values
        counts = pd.crosstab(bookings['userCode'], bookings['name']).reindex(columns=self.hotels_, fill_value=0)
        self.counts_ = counts
        self.prefs_ = counts.div(counts.sum(axis=1), axis=0).values.astype(np.float32)
        norms = np.linalg.norm(self.prefs_, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        unit = self.prefs_ / norms
        self.sim_ = (unit @ unit.T).astype(np.float32)        # cosine similarity between users
        np.fill_diagonal(self.sim_, 0.0)
        self.user_index_ = {u: i for i, u in enumerate(counts.index)}
        return self

    def _cf(self, i):
        sims = self.sim_[i]
        k = int(min(self.k_neighbors, len(sims) - 1))
        idx = np.argpartition(-sims, k)[:k]
        w = sims[idx]
        if w.sum() <= 0:
            return self.popularity_
        return (w @ self.prefs_[idx]) / w.sum()

    def scores(self, user):
        """Return (scores per hotel as a Series, is_cold_start)."""
        i = self.user_index_.get(user)
        if i is None:
            return pd.Series(self.popularity_, index=self.hotels_), True
        total = self.w_cf + self.w_history + self.w_pop
        if total <= 0:
            s = self.popularity_
        else:
            s = (self.w_cf * self._cf(i) + self.w_history * self.prefs_[i] + self.w_pop * self.popularity_) / total
        return pd.Series(np.asarray(s, dtype=float) + 1e-9 * self.popularity_, index=self.hotels_), False

    def rank(self, user, origin=None):
        """Ordered list of eligible hotels (best first)."""
        s, _ = self.scores(user)
        if origin is not None:
            s = s[self.catalog_.loc[s.index, 'place'].values != origin]
        return s.sort_values(ascending=False).index.tolist()

    def recommend(self, user, origin=None, destination=None, max_price=None, k=3):
        """Top-k suggestions with city, price and a human-readable reason."""
        s, cold = self.scores(user)
        cat = self.catalog_.loc[s.index]
        mask = np.ones(len(s), dtype=bool)
        if origin:
            mask &= cat['place'].values != origin
        if destination:
            mask &= cat['place'].values == destination
        if max_price is not None:
            mask &= cat['price'].values <= float(max_price)
        top = s[mask].sort_values(ascending=False).head(int(k))
        rows = []
        for hotel, score in top.items():
            stays = 0 if cold else int(self.counts_.loc[user, hotel])
            if cold:
                reason = 'Popular with all travellers'
            elif stays > 0:
                reason = f'You have stayed here {stays} time(s)'
            else:
                reason = 'Popular with travellers similar to you'
            rows.append({'hotel': hotel, 'city': cat.loc[hotel, 'place'],
                         'price_per_night': round(float(cat.loc[hotel, 'price']), 2),
                         'score': round(float(score), 4), 'reason': reason})
        return pd.DataFrame(rows, columns=['hotel', 'city', 'price_per_night', 'score', 'reason'])


class SVDRecommender:
    """Matrix factorisation: low-rank reconstruction of the user x hotel preference matrix."""

    def __init__(self, n_components=3):
        self.n_components = n_components

    def fit(self, bookings, catalog):
        self.catalog_ = catalog.set_index('name')[['place', 'price']].copy()
        self.hotels_ = list(self.catalog_.index)
        counts = pd.crosstab(bookings['userCode'], bookings['name']).reindex(columns=self.hotels_, fill_value=0)
        prefs = counts.div(counts.sum(axis=1), axis=0).values
        self.mean_ = prefs.mean(axis=0)
        U, S, Vt = np.linalg.svd(prefs - self.mean_, full_matrices=False)
        n = self.n_components
        self.recon_ = (U[:, :n] * S[:n]) @ Vt[:n] + self.mean_
        pop = bookings['name'].value_counts().reindex(self.hotels_, fill_value=0).astype(float)
        self.popularity_ = (pop / pop.sum()).values
        self.user_index_ = {u: i for i, u in enumerate(counts.index)}
        return self

    def rank(self, user, origin=None):
        i = self.user_index_.get(user)
        s = pd.Series(self.popularity_ if i is None else self.recon_[i] + 1e-9 * self.popularity_, index=self.hotels_)
        if origin is not None:
            s = s[self.catalog_.loc[s.index, 'place'].values != origin]
        return s.sort_values(ascending=False).index.tolist()
