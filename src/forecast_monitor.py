"""Descriptive live-forecast monitoring; never mixes retrospective backtests."""
from __future__ import annotations

import numpy as np
import pandas as pd


def summarize_live(history: pd.DataFrame, data_through: str) -> pd.DataFrame:
    """One row per archived model version; missing outcomes are never zero-filled."""
    columns = ['model_version', 'data_through', 'recorded', 'observed', 'pending',
               'excluded', 'invalid_outcomes', 'interval_rows', 'mae', 'rmse', 'bias',
               'interval_coverage', 'mean_interval_width', 'status']
    if history.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for version, group in history.groupby('model_version', dropna=False):
        completed = group[group.outcome_status == 'observed'].copy()
        values = completed[['predicted_k', 'actual_k']].apply(pd.to_numeric, errors='coerce').astype(float)
        valid = np.isfinite(values).all(axis=1) & (values >= 0).all(axis=1)
        completed = completed.loc[valid]
        error = values.loc[valid, 'predicted_k'] - values.loc[valid, 'actual_k']
        bounds = completed[['lower_k', 'upper_k']].apply(pd.to_numeric, errors='coerce').astype(float)
        usable = np.isfinite(bounds).all(axis=1) & (bounds.lower_k >= 0) & (bounds.upper_k >= bounds.lower_k)
        bounded = bounds.loc[usable]
        actual = values.loc[bounded.index, 'actual_k']
        n = len(completed)
        rows.append(dict(model_version=version, data_through=data_through,
                         recorded=len(group), observed=n,
                         pending=int((group.outcome_status == 'pending').sum()),
                         excluded=int((~group.outcome_status.isin(['pending', 'observed'])).sum()),
                         invalid_outcomes=int((~valid).sum()), interval_rows=len(bounded),
                         mae=error.abs().mean(), rmse=np.sqrt((error**2).mean()), bias=error.mean(),
                         interval_coverage=((actual >= bounded.lower_k) & (actual <= bounded.upper_k)).mean() if len(bounded) else np.nan,
                         mean_interval_width=(bounded.upper_k-bounded.lower_k).mean(),
                         status='awaiting_outcomes' if not n else 'limited_sample' if n < 30 else 'descriptive_only'))
    return pd.DataFrame(rows, columns=columns)
