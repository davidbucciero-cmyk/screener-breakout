import logging

import numpy as np

log = logging.getLogger(__name__)

QUANTILES = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
# Queue de distribution hors [q10, q90] : on borne P(hausse) plutot que d'extrapoler.
TAIL_PROB = 0.05


def prob_up(last_close, quantile_values, levels=QUANTILES):
    """P(close[t+1] > close[t]) a partir des quantiles predits.

    On interpole la fonction de repartition F aux quantiles connus puis P(hausse) = 1 - F(last_close).
    """
    v = np.sort(np.asarray(quantile_values, dtype=float))
    cdf = np.interp(last_close, v, levels, left=TAIL_PROB, right=1 - TAIL_PROB)
    return float(1 - cdf)


class ChronosForecaster:
    """Wrapper zero-shot autour de Chronos-Bolt (poids telecharges depuis HuggingFace)."""

    def __init__(self, model_name='amazon/chronos-bolt-small', device='cpu'):
        import torch
        from chronos import BaseChronosPipeline
        self._torch = torch
        log.info(f'Chargement {model_name} sur {device}')
        self.pipeline = BaseChronosPipeline.from_pretrained(model_name, device_map=device, torch_dtype=torch.float32)

    def predict_quantiles(self, contexts):
        """contexts : liste de np.ndarray 1D (prix). Retourne un array (n, len(QUANTILES)) pour t+1."""
        tensors = [self._torch.tensor(c, dtype=self._torch.float32) for c in contexts]
        q, _ = self.pipeline.predict_quantiles(tensors, prediction_length=1, quantile_levels=QUANTILES)
        return q[:, 0, :].numpy()
